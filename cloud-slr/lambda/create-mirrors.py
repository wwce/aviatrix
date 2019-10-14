import boto3
import logging
import ssl
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
gcontext = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get constants from environ variables
region = os.environ['region']
nlb_arn = os.environ['nlb_arn']
vpc_id = os.environ['vpc_id']

ec2_client = boto3.client('ec2')
session = boto3.Session(region_name='eu-west-1')

NITRO_INSTANCES = [
    'a1', 'c5', 'c5d', 'c5n', 'i3en', 'm5', 'm5a', 'm5ad', 'm5d', 'p3dn.24xlarge',
    'r5', 'r5a', 'r5ad', 'r5d', 't3', 't3a', 'z1d' 'c5.metal', 'c5n.metal', 'i3.metal',
    'i3en.metal', 'm5.metal', 'm5d.metal', 'r5.metal', 'r5d.metal', 'u-6tb1.metal',
    'u-9tb1.metal', 'u-12tb1.metal', 'z1d.metal'
]

def create_mirror_target_sg(session, region, target_vpc_id):
    ec2_client = session.client('ec2', region_name=region)

    sg_id = ec2_client.create_security_group(
        GroupName='grp-SLR-panw',
        Description='SLR-panw',
        VpcId=target_vpc_id
    )['GroupId']

    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'FromPort': 4789,
                'ToPort': 4789,
                'IpProtocol': 'udp',
                'IpRanges': [
                    {
                        'CidrIp': '10.0.0.0/8'
                    },
                    {
                        'CidrIp': '172.16.0.0/12'
                    },
                    {
                        'CidrIp': '192.168.0.0/16'
                    }
                ]
            }
        ]
    )


def create_traffic_mirror_target():
    try:
        target_id = ec2_client.create_traffic_mirror_target(
            NetworkLoadBalancerArn=nlb_arn, Description='PanwSLR mirror target')
        if target_id:
            return target_id
        else:
            return
    except:
        logger.info('Failed to get traffic mirror target')
        return


def create_filters(filter_id,direction,rule_num,protocol='6',dest_cidr='0.0.0.0/0',src_cidr='0.0.0.0/0'):


    ec2_client.create_traffic_mirror_filter_rule(
        TrafficMirrorFilterId=filter_id,
        TrafficDirection=direction,
        RuleNumber=rule_num,
        RuleAction='accept',
        DestinationPortRange={
            'FromPort' : 1,
            'ToPort' : 65000
        },
        SourcePortRange={
            'FromPort': 1,
            'ToPort': 65000
        },
        Protocol=protocol,
        DestinationCidrBlock='dest_cidr',
        SourceCidrBlock='src_cidr',
        Description='string'
    )

def create_mirror_session(session, region, mirror_target_id, mirror_filter_id, instance):
    ec2_client = session.client('ec2', region_name=region)

    return ec2_client.create_traffic_mirror_session(
        NetworkInterfaceId=instance['NetworkInterfaces'][0]['NetworkInterfaceId'],
        TrafficMirrorTargetId=mirror_target_id,
        TrafficMirrorFilterId=mirror_filter_id,
        SessionNumber=1
    )['TrafficMirrorSession']['TrafficMirrorSessionId']

def get_tagged_interfaces(tagname,tagvalue):
    try:
        interfaces_to_mirror = ec2_client.describe_network_interfaces(
        Filters=[{'Name': tagname, 'Values': [tagvalue]}])
        logger.info("Describe network interfaces response: {}".format(interfaces_to_mirror.get('NetworkInterfaces')))
        return interfaces_to_mirror.get('NetworkInterfaces')
    except Exception as err:
        logger.info('Got error describing interfaces to mirror {}'.format(err))
        return

def get_ec2_instances_by_region(region):
    ec2_client = boto3.client('ec2', region_name=region)

    instances = []

    response = ec2_client.describe_instances(MaxResults=1000)

    for reservation in response['Reservations']:
        instances.extend(reservation['Instances'])

    while response.get('NextToken'):
        response = ec2_client.describe_instances(
            NextToken=response.get('NextToken'),
            MaxResults=1000
        )

        for reservation in response['Reservations']:
            instances.extend(reservation['Instances'])

    return instances


def create_mirror_filter(session, region):
    client = boto3.client('ec2', region_name='eu-west-1')

    try:
        filter_id = client.create_traffic_mirror_filter()['TrafficMirrorFilter']['TrafficMirrorFilterId']
    except Exception as err:
        logger.info('Got err {}'.format(err))


    ec2_client.create_traffic_mirror_filter_rule(
        TrafficMirrorFilterId=filter_id,
        TrafficDirection='ingress',
        RuleNumber=1,
        RuleAction='accept',
        DestinationCidrBlock='0.0.0.0/0',
        SourceCidrBlock='0.0.0.0/0'
    )

    ec2_client.create_traffic_mirror_filter_rule(
        TrafficMirrorFilterId=filter_id,
        TrafficDirection='egress',
        RuleNumber=1,
        RuleAction='accept',
        DestinationCidrBlock='0.0.0.0/0',
        SourceCidrBlock='0.0.0.0/0'
    )

    return filter_id


def is_nitro_instance(instance):
    instance_type = instance['InstanceType']
    for nitro_type in NITRO_INSTANCES:
        if nitro_type in instance_type:
            return True

    return False

def is_tagged_for_mirror(instance,tag,value):
    tags = instance.get('Tags')

    pass



def main():
    client = boto3.client('ec2')

    ec2_instances = get_ec2_instances_by_region(region)

    instances_running_nitro = []
    for instance in ec2_instances:
        if is_nitro_instance(instance) and is_tagged_for_mirror(instance):
            instances_running_nitro.append(instance)

    # interfaces_tagged_for_mirror = get_tagged_interfaces('tag:PanwSLR','mirror')
    # contstants
    filter_direction = ('Ingress', 'Egress')
    filter_id = create_mirror_filter(session, region)
    index = 0
    for direction in filter_direction:
        create_filters(filter_id, direction, index)
        index += 1
    interfaces_to_mirror = get_tagged_interfaces()
    # traffic_mirror_target_id = create_traffic_mirror_target()
    # if interfaces_to_mirror:
    #     # Create filter
    #     for interface in interfaces_to_mirror:
    #         session_description = 'PanwSLR-Mirror-session'+interface
    #         ec2_client.create_traffic_mirror_session(NetworkInterfaceId=interface,
    #                                                  TrafficMirrorTargetId=traffic_mirror_target_id,
    #                                                  TrafficMirrorFilterId=filter_id,
    #                                                  SessionNumber=1, Description=session_description)



if __name__ == '__main__':
    main()