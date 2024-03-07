#!/usr/bin/env python
""" This script is used to compare the shape average and bandwidth for Cisco routers.
    It saves the results to a csv file.

    History:
"""
__author__ = "NAME HERE"
__credits__ = ["NAME HERE"]
__version__ = "1.0.1"
__maintainer__ = "NAME HERE"
__email__ = "EMAIL HERE"
__status__ = "Development"

import time
import argparse
import logging
import datetime
import csv
import pandas as pd
import colorama
import concurrent.futures as cf

from tqdm import tqdm
from ciscoconfparse import CiscoConfParse
from logging.handlers import RotatingFileHandler
from pytz import timezone
from netmiko import (
    ConnectHandler,
    NetMikoAuthenticationException,
    NetMikoTimeoutException,
    NetmikoBaseException
    )
from configparser import ConfigParser


# Get credentials
config = ConfigParser()
config.read('/path/to/config.ini')

# Set eastern timezone
EST = timezone('America/New_York')

# Netmiko exceptions
netmiko_exceptions = (
    NetMikoTimeoutException,
    NetMikoAuthenticationException,
    NetmikoBaseException
)

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename='/path/to/logs/shape.log',
    encoding='utf-8',
    mode='a+',
    maxBytes=157286400,
    backupCount=5
)
handler.setFormatter(
    logging.Formatter('%(levelname)s - %(asctime)s: %(message)s')
)
logger.addHandler(handler)


def check_shape_bandwidth(device):
    """ Compare the bandwidth to the shape average in the device config. The
        logic for the script follows:

        1.	Check hostname for 'be'
        2.	Check if bandwidth or shape average statements are missing
        3.	Check for more than 1 bandwidth (unique values)
        4.	Check for more than 1 shape average statement (include duplicates)
        5.	If both bandwidth & shape average exist, convert bandwidth to
            megabytes and compare with shape average (allowing a delta of 1)


    Args:
        device (string): ip address of router

    Returns:
        results (dict): (ip, hostname, bandwidth, shape average, test results,
                        comments, current time)
    """

    # Host credentials
    host = {
        "host": device,
        "port": 22,
        "username": config['CREDENTIALS']['username'],
        "password": config['CREDENTIALS']['password'],
        "secret": config['CREDENTIALS']['password'],
        "device_type": "cisco_ios",
        "fast_cli": "False"
    }

    # Initialize list to store host results
    record = {}
    record['ip'] = device

    try:
        # Connect to host
        net_connect = ConnectHandler(**host)
        logger.info(f'Connected to {device}.')

        try:
            # Enter enable mode
            net_connect.enable()

            # Get hostname
            hostname_output = net_connect.send_command(
                'show run | include hostname'
            )
            hostname_lst = hostname_output.split(' ')
            hostname = hostname_lst[-1]

            record['hostname'] = hostname

            # Check if hostname contains 'be'
            if 'be' in hostname:
                logger.info(
                    f'{device} - {hostname} bypassed because of best '
                    'effort services.'
                )
                record['bandwidth'] = 'see comment'
                record['shape_avg'] = 'see comment'
                record['results'] = 'Skipped'
                record['comments'] = (
                    f'{host["host"]} - {hostname} bypassed because of best'
                    ' effort services.')

            else:
                # Check for bandwidth and shape average statement in config
                bandwidth_output = net_connect.send_command(
                    'show run | include ^ bandwidth'
                )
                shape_output = net_connect.send_command(
                    'show run | include shape average'
                )

                if (bandwidth_output == '' and shape_output == ''):
                    logger.error(
                        f'{device} - {hostname} missing bandwidth and'
                        ' shape average statements!'
                    )
                    record['bandwidth'] = None
                    record['shape_avg'] = None
                    record['results'] = 'Fail'
                    record['comments'] = (
                        f'{device} - {hostname} missing bandwidth and'
                        ' shape average statements!')

                elif (bandwidth_output != '' and shape_output == ''):
                    logger.error(
                        f'{device} - {hostname} missing shape average'
                        f' statement! Bandwidth output: {bandwidth_output}'
                    )
                    record['bandwidth'] = 'see comments'
                    record['shape_avg'] = None
                    record['results'] = 'Fail'
                    record['comments'] = (
                        f'{device} - {hostname} missing shape average'
                        f' statement! Bandwidth output: {bandwidth_output}'
                    )

                elif (bandwidth_output == '' and shape_output != ''):
                    logger.error(
                        f'{device} - {hostname} missing bandwidth'
                        f' statement! Shape average output: {shape_output}'
                    )
                    record['bandwidth'] = None
                    record['shape_avg'] = 'see comment'
                    record['results'] = 'Fail'
                    record['comments'] = (
                        f'{device} - {hostname} missing shape average'
                        f' statement! Shape average output: {shape_output}'
                    )

                else:

                    bandwidth_lst = bandwidth_output.split(' ')
                    bandwidth_full_lst = ' '.join(bandwidth_lst).split()
                    bandwidth_txt_lst = [*set(bandwidth_full_lst)]

                    bandwidth_txt_lst.remove('bandwidth')

                    # Check for more than 1 bandwidth statement
                    if len(bandwidth_txt_lst) >= 2:
                        logger.error(
                            f'{device} - {hostname} has more than 1'
                            f' bandwidth: {bandwidth_txt_lst}')
                        record['bandwidth'] = 'see comment'
                        record['shape_avg'] = 'see comment'
                        record['results'] = 'Fail'
                        record['comments'] = (
                            f'{device} - {hostname} has more than 1'
                            f' bandwidth: {bandwidth_txt_lst}. Shape average'
                            f' output: {shape_output}'
                        )
                    else:

                        shape_lst = shape_output.split(' ')
                        shape_txt_lst = ' '.join(shape_lst).split()

                        while ('shape' in shape_txt_lst):
                            shape_txt_lst.remove('shape')

                        while ('average' in shape_txt_lst):
                            shape_txt_lst.remove('average')

                        # Check for more than 1 shape average
                        if len(shape_txt_lst) >= 2:
                            logger.error(
                                f'{device} - {hostname} has more than 1'
                                f' shape average statement: {shape_txt_lst}')
                            record['bandwidth'] = bandwidth_txt_lst[0]
                            record['shape_avg'] = 'see comment'
                            record['results'] = 'Fail'
                            record['comments'] = (
                                f'{device} - {hostname} has more than 1'
                                f' shape average statement: {shape_txt_lst}'
                            )

                        else:
                            shape_txt = ' '.join(shape_txt_lst).split()[-1]
                            shape = int(shape_txt)

                            bandwidth_txt = ' '.join(bandwidth_lst).split()[-1]
                            bandwidth = int(bandwidth_txt)

                            # Convert bandwidth from kb to Mb to match
                            # shape average units
                            bandwidth_to_mb = bandwidth * 1000

                            # Compare bandwidth to the shape average
                            if (bandwidth_to_mb-shape == 0):
                                logger.info(
                                    f'{device} - {hostname}(Exact Match)'
                                    f' Bandwidth = {bandwidth_to_mb}'
                                    f' Shape = {shape}'
                                )
                                record['bandwidth'] = bandwidth_to_mb
                                record['shape_avg'] = shape
                                record['results'] = 'Pass'
                                record['comments'] = (
                                    f'{device} - {hostname}(Exact Match)'
                                    f' Bandwidth = {bandwidth_to_mb}'
                                    f' Shape = {shape}'
                                )

                            elif (bandwidth_to_mb-shape == 1):
                                logger.info(
                                    f'{device} - {hostname} (Delta = 1)'
                                    f' Bandwidth = {bandwidth_to_mb}'
                                    f' Shape = {shape}'
                                )
                                record['bandwidth'] = bandwidth_to_mb
                                record['shape_avg'] = shape
                                record['results'] = 'Pass'
                                record['comments'] = (
                                    f'{device} - {hostname} (Delta = 1)'
                                    f' Bandwidth = {bandwidth_to_mb}'
                                    f' Shape = {shape}'
                                )

                            else:
                                logger.error(
                                    f'{device} - {hostname} (Delta > 1)'
                                    f' Bandwidth{bandwidth_to_mb}'
                                    f' and shape{shape} mismatch!'
                                )
                                record['bandwidth'] = bandwidth_to_mb
                                record['shape_avg'] = shape
                                record['results'] = 'Pass'
                                record['comments'] = (
                                    f'{device} - '
                                    f'{hostname} (Delta > 1) Bandwidth'
                                    f' {bandwidth_to_mb} and shape{shape}'
                                    f' mismatch!'
                                )

        except Exception as e:
            logger.error(f'Exception on {device} - {hostname}: {e}')
            record['bandwidth'] = 'see comment'
            record['shape_avg'] = 'see comment'
            record['results'] = 'Fail'
            record['comments'] = (
                f'Exception on {device} - {hostname}: {e}'
            )

        # Close ssh session
        net_connect.disconnect()
        logger.info('\nSSH Connection closed.')

    except netmiko_exceptions as e:
        logger.error(
            f'Failed to connect to {device}; Exception: {e}'
        )
        record['bandwidth'] = 'see comment'
        record['shape_avg'] = 'see comment'
        record['results'] = 'Fail'
        record['comments'] = f'Exception on {device}: {e}'

    record['timestamp'] = datetime.datetime.now(tz=EST)

    return record


def main():
    # Set up optional argument for local run
    ap = argparse.ArgumentParser()
    _ = ap.add_argument(
        '--man',
        action='store_true',
        help='Run script manually w/ progress bar'
    )
    args = ap.parse_args()

    # Start timer
    start = time.perf_counter()
    logger.info('Running shaper average / bandwidth check for routers...')

    # Reading CSV file for device data
    data = pd.read_csv('/path/to/csv/file/with/ip/list')

    # converting csv data to list
    devices = data['ip'].tolist()

    # Create csv file to store results
    filename = '/path/to/output/csv/file'

    # Open file to write results
    with open(filename, 'w', newline='') as csvfile:

        # field names
        FIELDS = [
            'ip',
            'hostname',
            'bandwidth',
            'shape_avg',
            'results',
            'comments',
            'timestamp'
        ]

        # Create csv writer object
        csvwriter = csv.DictWriter(csvfile, fieldnames=FIELDS)

        # Wrie the fields
        csvwriter.writeheader()

        with cf.ProcessPoolExecutor(max_workers=12) as executor:
            if args.man:  # for running in command line w/ progress bar
                results = list(
                    tqdm(
                        executor.map(
                            check_shape_bandwidth, devices
                        ),
                        total=len(devices),
                        colour='green'
                    )
                )
                csvwriter.writerows(results)
            else:  # for running programmatically
                for result in executor.map(check_shape_bandwidth, devices):
                    csvwriter.writerow(result)

    # End timer
    end = time.perf_counter()

    logger.info(
        'Finished collecting shape avg and bandwidth data from a list of'
        f' {len(devices)} routers in {round(end-start, 2)} second(s)'
        )

if __name__ == '__main__':
    main()