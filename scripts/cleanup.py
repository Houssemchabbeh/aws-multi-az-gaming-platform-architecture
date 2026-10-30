"""Delete every AWS resource of the HA gaming platform (boto3 version of
`terraform destroy`).

Usage (from the repo folder, after pasting fresh Learner Lab credentials):
    python scripts/cleanup.py          # asks you to type 'delete' first
    python scripts/cleanup.py --yes    # no prompt

Resources are found by the names Terraform gives them (prefix "gaming").
Takes ~15 min: RDS and Redis are the slow ones. Safe to re-run if it stops
halfway: anything already deleted is skipped.

Afterwards the local Terraform state is out of date: delete terraform.tfstate*
(or run `terraform apply` to rebuild everything from scratch).
"""
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
PREFIX = "gaming"
ASG_NAME = f"{PREFIX}-asg"
DB_ID = f"{PREFIX}-db"
REDIS_ID = f"{PREFIX}-redis"
NLB_NAME = f"{PREFIX}-nlb"
TARGET_GROUPS = [f"{PREFIX}-tg-tcp80", f"{PREFIX}-tg-udp3478"]

ec2 = boto3.client("ec2", region_name=REGION)
autoscaling = boto3.client("autoscaling", region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)
elasticache = boto3.client("elasticache", region_name=REGION)
rds = boto3.client("rds", region_name=REGION)
efs = boto3.client("efs", region_name=REGION)

SLOW_WAIT = {"Delay": 30, "MaxAttempts": 60}  # up to 30 min


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def call(fn, **kwargs):
    """Run an AWS call; a 'not found' error means it is already deleted."""
    try:
        return fn(**kwargs)
    except ClientError as e:
        if "NotFound" in e.response["Error"]["Code"]:
            return None
        raise


def retry(fn, what, timeout=900, **kwargs):
    """Retry while AWS says something still depends on the resource
    (e.g. network interfaces of a deleted service are still being released)."""
    start = time.time()
    while True:
        try:
            return call(fn, **kwargs)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("DependencyViolation", "ResourceInUse") or time.time() - start > timeout:
                raise
            log(f"  {what} still in use, retrying in 15s...")
            time.sleep(15)


def wait_until(check, what, timeout=900, every=15):
    log(f"  waiting for {what}...")
    start = time.time()
    while not check():
        if time.time() - start > timeout:
            raise TimeoutError(f"Timed out waiting for {what}")
        time.sleep(every)


def asg_exists():
    return bool(autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[ASG_NAME])["AutoScalingGroups"])


def main():
    if "--yes" not in sys.argv:
        answer = input(f"This permanently deletes all '{PREFIX}' resources in {REGION}. "
                       "Type 'delete' to continue: ")
        if answer.strip() != "delete":
            print("Cancelled.")
            return

    # 1. Start the slow deletions first, so they run in parallel in AWS.
    db = call(rds.describe_db_instances, DBInstanceIdentifier=DB_ID)
    if db:
        status = db["DBInstances"][0]["DBInstanceStatus"]
        if status in ("starting", "stopping"):
            wait_until(lambda: rds.describe_db_instances(DBInstanceIdentifier=DB_ID)
                       ["DBInstances"][0]["DBInstanceStatus"] in ("available", "stopped"),
                       f"RDS to finish '{status}'")
        if status != "deleting":
            log("RDS: deleting gaming-db (no final snapshot)")
            rds.delete_db_instance(DBInstanceIdentifier=DB_ID, SkipFinalSnapshot=True,
                                   DeleteAutomatedBackups=True)

    redis = call(elasticache.describe_replication_groups, ReplicationGroupId=REDIS_ID)
    if redis and redis["ReplicationGroups"][0]["Status"] != "deleting":
        log("Redis: deleting gaming-redis")
        elasticache.delete_replication_group(ReplicationGroupId=REDIS_ID)

    # 2. Game servers: Auto Scaling group (terminates its instances) + launch template
    if asg_exists():
        log("Auto Scaling group: deleting gaming-asg and its instances")
        autoscaling.delete_auto_scaling_group(AutoScalingGroupName=ASG_NAME, ForceDelete=True)
        wait_until(lambda: not asg_exists(), "Auto Scaling group to be deleted")
    for lt in ec2.describe_launch_templates()["LaunchTemplates"]:
        if lt["LaunchTemplateName"].startswith(f"{PREFIX}-lt-"):
            log(f"Launch template: deleting {lt['LaunchTemplateName']}")
            ec2.delete_launch_template(LaunchTemplateId=lt["LaunchTemplateId"])

    # 3. Load balancer (its listeners are deleted with it), then target groups
    lbs = call(elbv2.describe_load_balancers, Names=[NLB_NAME])
    if lbs:
        arn = lbs["LoadBalancers"][0]["LoadBalancerArn"]
        log("NLB: deleting gaming-nlb")
        elbv2.delete_load_balancer(LoadBalancerArn=arn)
        elbv2.get_waiter("load_balancers_deleted").wait(LoadBalancerArns=[arn])
    for name in TARGET_GROUPS:
        tgs = call(elbv2.describe_target_groups, Names=[name])
        if tgs:
            log(f"Target group: deleting {name}")
            retry(elbv2.delete_target_group, name, TargetGroupArn=tgs["TargetGroups"][0]["TargetGroupArn"])

    # 4. EFS: mount targets first, then the file system
    for fs in efs.describe_file_systems()["FileSystems"]:
        if fs.get("Name") != f"{PREFIX}-efs":
            continue
        fs_id = fs["FileSystemId"]
        for mt in efs.describe_mount_targets(FileSystemId=fs_id)["MountTargets"]:
            log(f"EFS: deleting mount target {mt['MountTargetId']} ({mt['AvailabilityZoneName']})")
            call(efs.delete_mount_target, MountTargetId=mt["MountTargetId"])
        wait_until(lambda: not efs.describe_mount_targets(FileSystemId=fs_id)["MountTargets"],
                   "EFS mount targets to be deleted")
        log(f"EFS: deleting file system {fs_id}")
        call(efs.delete_file_system, FileSystemId=fs_id)

    # 5. Wait for Redis and RDS, then remove their subnet groups
    log("Redis: waiting for deletion to finish (~5-10 min)")
    elasticache.get_waiter("replication_group_deleted").wait(
        ReplicationGroupId=REDIS_ID, WaiterConfig=SLOW_WAIT)
    log("Redis: deleting subnet group")
    call(elasticache.delete_cache_subnet_group, CacheSubnetGroupName=f"{PREFIX}-cache-subnets")

    log("RDS: waiting for deletion to finish (~5-15 min)")
    rds.get_waiter("db_instance_deleted").wait(DBInstanceIdentifier=DB_ID, WaiterConfig=SLOW_WAIT)
    log("RDS: deleting subnet group")
    call(rds.delete_db_subnet_group, DBSubnetGroupName=f"{PREFIX}-db-subnets")

    # 6. Network: security groups, Internet Gateway, route table, subnets, VPC
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "tag:Name", "Values": [f"{PREFIX}-vpc"]}])["Vpcs"]
    for vpc in vpcs:
        vpc_id = vpc["VpcId"]
        vpc_filter = [{"Name": "vpc-id", "Values": [vpc_id]}]

        groups = [g for g in ec2.describe_security_groups(Filters=vpc_filter)["SecurityGroups"]
                  if g["GroupName"] != "default"]
        # Security groups reference each other, so remove their inbound rules first.
        for g in groups:
            if g["IpPermissions"]:
                ec2.revoke_security_group_ingress(GroupId=g["GroupId"], IpPermissions=g["IpPermissions"])
        for g in groups:
            log(f"Security group: deleting {g['GroupName']}")
            retry(ec2.delete_security_group, g["GroupName"], GroupId=g["GroupId"])

        igws = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])["InternetGateways"]
        for igw in igws:
            log(f"Internet Gateway: detaching and deleting {igw['InternetGatewayId']}")
            retry(ec2.detach_internet_gateway, "Internet Gateway",
                  InternetGatewayId=igw["InternetGatewayId"], VpcId=vpc_id)
            call(ec2.delete_internet_gateway, InternetGatewayId=igw["InternetGatewayId"])

        for rt in ec2.describe_route_tables(Filters=vpc_filter)["RouteTables"]:
            if any(a.get("Main") for a in rt["Associations"]):
                continue  # the VPC's main route table is deleted with the VPC
            for a in rt["Associations"]:
                ec2.disassociate_route_table(AssociationId=a["RouteTableAssociationId"])
            log(f"Route table: deleting {rt['RouteTableId']}")
            call(ec2.delete_route_table, RouteTableId=rt["RouteTableId"])

        for subnet in ec2.describe_subnets(Filters=vpc_filter)["Subnets"]:
            log(f"Subnet: deleting {subnet['SubnetId']} ({subnet['AvailabilityZone']})")
            retry(ec2.delete_subnet, "subnet", SubnetId=subnet["SubnetId"])

        log(f"VPC: deleting {vpc_id}")
        retry(ec2.delete_vpc, "VPC", VpcId=vpc_id)

    log("Done. All gaming resources deleted. Delete terraform.tfstate* (Terraform state is now outdated).")


if __name__ == "__main__":
    main()
