"""Stop, start and test the HA gaming platform built by Terraform.

Usage (from the repo folder, after pasting fresh Learner Lab credentials):
    python scripts/stop_start.py stop    # scale game servers to 0, stop RDS
    python scripts/stop_start.py start   # start RDS, bring back 2 game servers, then test
    python scripts/stop_start.py test    # only run the connectivity tests

The NLB, ElastiCache Redis and EFS have no "stop" in AWS, so they keep
running (at a small cost) while the platform is stopped.
"""
import sys
import time
import urllib.request
import uuid

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
PREFIX = "gaming"
ASG_NAME = f"{PREFIX}-asg"
DB_ID = f"{PREFIX}-db"
REDIS_ID = f"{PREFIX}-redis"
NLB_NAME = f"{PREFIX}-nlb"
TARGET_GROUPS = [f"{PREFIX}-tg-tcp80", f"{PREFIX}-tg-udp3478"]
ASG_MIN, ASG_DESIRED, ASG_MAX = 2, 2, 6  # same values as compute.tf

autoscaling = boto3.client("autoscaling", region_name=REGION)
rds = boto3.client("rds", region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)
elasticache = boto3.client("elasticache", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)

# Runs on each game server through SSM. Bash's /dev/tcp opens a TCP
# connection, so no extra tools are needed on the instance.
CHECK_SCRIPT = """
R=$(timeout 5 bash -c 'exec 3<>/dev/tcp/REDIS_HOST/6379; printf "PING\\r\\n" >&3; head -c 7 <&3' 2>&1)
case "$R" in *PONG*) echo REDIS=OK ;; *) echo "REDIS=FAIL $R" ;; esac
timeout 5 bash -c '</dev/tcp/DB_HOST/5432' && echo DB=OK || echo DB=FAIL
mountpoint -q /mnt/efs && echo EFS=OK || echo EFS=FAIL
"""


# ---------- helpers ----------

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def wait_until(check, what, timeout=1200, every=20):
    """Call check() until it returns True; give up after `timeout` seconds."""
    log(f"Waiting for {what}...")
    start = time.time()
    while time.time() - start < timeout:
        if check():
            return True
        time.sleep(every)
    log(f"Timed out waiting for {what}")
    return False


def db_status():
    db = rds.describe_db_instances(DBInstanceIdentifier=DB_ID)["DBInstances"][0]
    return db["DBInstanceStatus"]


def asg_instances(in_service_only=True):
    """Instances of the Auto Scaling group as [(instance_id, az), ...]."""
    group = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[ASG_NAME])["AutoScalingGroups"][0]
    return sorted(
        (i["InstanceId"], i["AvailabilityZone"])
        for i in group["Instances"]
        if not in_service_only or i["LifecycleState"] == "InService"
    )


def healthy_count(tg_name):
    arn = elbv2.describe_target_groups(Names=[tg_name])["TargetGroups"][0]["TargetGroupArn"]
    targets = elbv2.describe_target_health(TargetGroupArn=arn)["TargetHealthDescriptions"]
    return sum(1 for t in targets if t["TargetHealth"]["State"] == "healthy")


def ssm_online(instance_ids):
    info = ssm.describe_instance_information(
        Filters=[{"Key": "InstanceIds", "Values": instance_ids}])["InstanceInformationList"]
    return sum(1 for i in info if i["PingStatus"] == "Online") == len(instance_ids)


def run_on(instance_id, script):
    """Run a shell script on an EC2 instance through SSM and return its output."""
    cmd = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": script.strip().splitlines()},
    )
    cmd_id = cmd["Command"]["CommandId"]
    for _ in range(30):
        time.sleep(2)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvocationDoesNotExist":
                continue
            raise
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            return inv["StandardOutputContent"] + inv["StandardErrorContent"]
    return ""


# ---------- actions ----------

def stop():
    log("Game servers: scaling the Auto Scaling group to 0 "
        "(instances are terminated; 'start' launches fresh ones from the launch template)")
    autoscaling.update_auto_scaling_group(
        AutoScalingGroupName=ASG_NAME, MinSize=0, DesiredCapacity=0)

    status = db_status()
    if status == "available":
        log("RDS: stopping (Multi-AZ stop takes ~5-10 min)")
        rds.stop_db_instance(DBInstanceIdentifier=DB_ID)
    else:
        log(f"RDS: status is '{status}', not stopping it")

    if wait_until(lambda: not asg_instances(in_service_only=False), "game servers to terminate"):
        log("Game servers: all terminated")
    if status in ("available", "stopping", "stopped"):
        if wait_until(lambda: db_status() == "stopped", "RDS to stop"):
            log("RDS: stopped (note: AWS starts a stopped DB again after 7 days)")

    log("Still running (AWS can't stop these): NLB, Redis, EFS")


def start():
    status = db_status()
    if status == "stopped":
        log("RDS: starting (takes ~10-15 min)")
        rds.start_db_instance(DBInstanceIdentifier=DB_ID)
    else:
        log(f"RDS: status is '{status}'")

    log(f"Game servers: scaling the Auto Scaling group back to {ASG_DESIRED}")
    autoscaling.update_auto_scaling_group(
        AutoScalingGroupName=ASG_NAME,
        MinSize=ASG_MIN, DesiredCapacity=ASG_DESIRED, MaxSize=ASG_MAX)

    # Both run in parallel in AWS; RDS is usually the slower one.
    if wait_until(lambda: all(healthy_count(tg) >= ASG_DESIRED for tg in TARGET_GROUPS),
                  "game servers to pass NLB health checks"):
        log("Game servers: healthy")
    if wait_until(lambda: db_status() == "available", "RDS to be available", timeout=1800):
        log("RDS: available")

    return test()


def test():
    results = []  # (check name, passed, detail)

    # 1. NLB target health
    for tg in TARGET_GROUPS:
        n = healthy_count(tg)
        results.append((f"Target group {tg} has {ASG_DESIRED} healthy targets", n >= ASG_DESIRED, f"{n} healthy"))

    # 2. Web page through the NLB, from this laptop
    dns = elbv2.describe_load_balancers(Names=[NLB_NAME])["LoadBalancers"][0]["DNSName"]
    zones = set()
    for _ in range(10):
        try:
            body = urllib.request.urlopen(f"http://{dns}", timeout=10).read().decode()
            zones.update(z for z in ("us-east-1a", "us-east-1b") if z in body)
        except OSError:
            pass
    results.append(("HTTP page through the NLB", bool(zones),
                    f"answered from {', '.join(sorted(zones)) or 'nowhere'}"))

    # 3. From inside each game server: Redis, RDS and EFS
    redis_host = elasticache.describe_replication_groups(ReplicationGroupId=REDIS_ID)[
        "ReplicationGroups"][0]["NodeGroups"][0]["PrimaryEndpoint"]["Address"]
    db_host = rds.describe_db_instances(DBInstanceIdentifier=DB_ID)["DBInstances"][0]["Endpoint"]["Address"]
    script = CHECK_SCRIPT.replace("REDIS_HOST", redis_host).replace("DB_HOST", db_host)

    instances = asg_instances()
    if not instances:
        results.append(("Game servers running", False, "no in-service instances"))
    else:
        wait_until(lambda: ssm_online([i for i, _ in instances]), "SSM agent on game servers",
                   timeout=300, every=10)
        for instance_id, az in instances:
            out = run_on(instance_id, script)
            for key, label in (("REDIS", "Redis PING -> PONG"),
                               ("DB", "RDS port 5432 reachable"),
                               ("EFS", "EFS mounted at /mnt/efs")):
                results.append((f"[{az} {instance_id}] {label}", f"{key}=OK" in out, ""))

    # 4. EFS is shared: write a file in one AZ, read it from the other
    if len(instances) >= 2:
        (a_id, a_az), (b_id, b_az) = instances[0], instances[-1]
        token = uuid.uuid4().hex
        run_on(a_id, f"echo {token} > /mnt/efs/connectivity-test.txt")
        out = run_on(b_id, "cat /mnt/efs/connectivity-test.txt; rm -f /mnt/efs/connectivity-test.txt")
        results.append((f"EFS shared: written in {a_az}, read back in {b_az}", token in out, ""))

    print("\n===== Connectivity test =====")
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    all_passed = all(passed for _, passed, _ in results)
    print(f"\n{'ALL PASSED' if all_passed else 'SOME CHECKS FAILED'}")
    return all_passed


if __name__ == "__main__":
    actions = {"stop": stop, "start": start, "test": test}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print(__doc__)
        sys.exit(2)
    sys.exit(0 if actions[sys.argv[1]]() is not False else 1)
