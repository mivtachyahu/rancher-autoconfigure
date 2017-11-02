#!/usr/bin/env python
"""Script to automatically add a docker host to rancher"""
# -*- coding: utf-8 -*-

import json
import fileinput
from time import sleep
import subprocess
import sys

import dbus
import boto3
import requests
from retry import retry


def get_instance_info(detail):
    """identify what instance we are running on"""
    self_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"
    return json.loads(requests.get(self_url).text)[detail]

@retry(tries=30, delay=10)
def wait_for_tags():
    """get tag on self"""
    ec2 = boto3.client(
        'ec2', region_name=get_instance_info("region"))
    response = ec2.describe_instances(
        InstanceIds=[get_instance_info("instanceId")])
    if "Tags" not in response['Reservations'][0]['Instances'][0]:
        raise Exception("Error! Instance has no tags")

def get_tag(tag_name):
    """get tag on self"""
    ec2 = boto3.client(
        'ec2', region_name=get_instance_info("region"))
    response = ec2.describe_instances(
        InstanceIds=[get_instance_info("instanceId")])
    return_value = None
    for tags in response['Reservations'][0]['Instances'][0]['Tags']:
        if tags['Key'] == tag_name:
            return_value = tags['Value']
    if return_value is not None:
        return return_value
    else:
        raise Exception("Error! Instance missing Tag %s" % tag_name)

def read_config():
    """read config file for rancher_url, rancher_key, rancher_secret,"""
    s3_client = boto3.client('s3')
    bucket = get_tag("Config_Bucket")
    path = get_tag("Config_Path")
    try:
        s3_client.download_file(
            bucket, path + '/rancher-secrets.json', '/etc/rancher-secrets.json')
    except Exception as e:
        sys.exit('Could not download s3://%s/%s/rancher-secrets.json - %s' %
                 (bucket, path, e))
    rancher_config = json.loads(open('/etc/rancher-secrets.json').read())
    return rancher_config['rancher_url'], rancher_config['rancher_key'], rancher_config['rancher_secret']


def split_url(url):
    """split url to protocol and host"""
    rancher_protocol, rancher_host = url.split("://")
    return rancher_protocol, rancher_host


def get_environment(rancher_protocol, rancher_key, rancher_secret, rancher_host):
    """get environment we're in"""
    url = "%s://%s:%s@%s/v1/projects" % (rancher_protocol,
                                         rancher_key, rancher_secret, rancher_host)
    response = requests.get(url)
    data = json.loads(response.text)
    rancher_environment = data['data'][0]['name']
    print "rancher_environment is %s" % rancher_environment
    return rancher_environment

def get_pid(name):
    try:
        response = subprocess.check_output(["pidof", name])
    except subprocess.CalledProcessError:
        return None
    return response

def start_service(service, process):
    """Starts service using dbus"""
    sysbus = dbus.SystemBus()
    systemd1 = sysbus.get_object(
        'org.freedesktop.systemd1', '/org/freedesktop/systemd1')
    manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
    manager.StartUnit(service, 'fail')
    print "Starting %s" % service
    while get_pid(process) is None:
        print "."
        sleep(5)


def add_labels(command):
    """Adds labels to the rancher join command"""
    instance_id = get_instance_info("instanceId")
    instance_region = get_instance_info("availabilityZone")
    host_labels = get_tag("Config_Host_Labels")
    command = command.replace(
        "--privileged", '--privileged -e CATTLE_HOST_LABELS="aws.instance_id=%s&aws.availability_zone=%s&%s"' % (instance_id, instance_region, host_labels))
    return command


def get_registration_command(rancher_protocol, rancher_key, rancher_secret, rancher_host):
    """now ask for a new registration key and wait until it becomes active"""
    url = "%s://%s:%s@%s/v1/registrationtokens" % (
        rancher_protocol, rancher_key, rancher_secret, rancher_host)
    response = requests.post(url, json={})
    key_active = False
    while not key_active:
        url = "%s://%s:%s@%s/v1/registrationtokens/%s" % (
            rancher_protocol, rancher_key, rancher_secret, rancher_host, response.json()['id'])
        print url
        if response.json()['state'] == 'active':
            key_active = True
            command = response.json()['command']
            command = add_labels(command)
            print "registration command is %s" % command
            return command
        else:
            sleep(0.1)
            response = requests.get(url)


if __name__ == '__main__':
    wait_for_tags()
    RANCHER_URL, RANCHER_KEY, RANCHER_SECRET = read_config()
    RANCHER_PROTOCOL, RANCHER_HOST = split_url(RANCHER_URL)
    ENVIRONMENT = get_environment(RANCHER_PROTOCOL, RANCHER_KEY, RANCHER_SECRET, RANCHER_HOST)
    subprocess.call(["systemctl", "daemon-reload"])
    start_service("docker.service", "/usr/bin/dockerd")
    subprocess.call(get_registration_command(
        RANCHER_PROTOCOL, RANCHER_KEY, RANCHER_SECRET, RANCHER_HOST), shell=True)
