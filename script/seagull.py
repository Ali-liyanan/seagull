#!/usr/bin/python
# coding: utf-8
# Copyright 2020 CMCC Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# NOTE: This feature is avaialble as ONAP CLI seagull
#
# Author: wutuo@chinamobile.com
#
import argparse
import json
import random
from time import sleep

import paramiko
import requests

SEAGULL_CLIENT_DEFAULT_PORT = 9000
SEAGULL_SERVER_DEFAULT_PORT = 9100

SEAGULL_CLIENT_CMD = 'cd /opt/seagull/data/{0}-env/run && sudo ./start_client.ksh {1}:' + \
                     str(SEAGULL_CLIENT_DEFAULT_PORT)
SEAGULL_SERVER_CMD = 'cd /opt/seagull/data/{0}-env/run && sudo ./start_server.ksh {1}:' + \
                     str(SEAGULL_SERVER_DEFAULT_PORT)

SEAGULL_CLIENT_RESULT_FILE_CMD = r"sudo ls -lt /opt/seagull/data/%s-env/logs | grep client-protocol-stat.%s " + \
                                 "| head -n 1 |awk '{print $9}'"
SEAGULL_CLIENT_RESULT_FILTER_CMD = r"sudo cat /opt/seagull/data/%s-env/logs/%s | awk 'END {print}' | cut -d';' -f 1,2"

SEAGULL_SERVER_RESULT_FILE_CMD = r"sudo ls -lt /opt/seagull/data/%s-env/logs | grep server-protocol-stat.%s " + \
                                 "| head -n 1 |awk '{print $9}'"
SEAGULL_SERVER_RESULT_FILTER_CMD = r"sudo cat /opt/seagull/data/%s-env/logs/%s | awk 'END {print}' | cut -d';' -f 1,2"


class SeagullException(Exception):
    def __init__(self, code, message):
        super(SeagullException, self).__init__()
        self.code = code
        self.message = message


class Linux(object):
    def __init__(self, ip, username=None, password=None, timeout=30):
        self.ip = ip
        self.username = username
        self.password = password
        self.timeout = timeout
        self.try_times = 3
        self.ssh_client = None

    def connect(self):
        while True:
            try:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.ssh_client.connect(hostname=self.ip, username=self.username, password=self.password)
                # print("Successful connection->".format(self.ip))
                return
            except Exception as e1:
                if self.try_times != 0:
                    print('connect %s failed，try to retry' % self.ip)
                    self.try_times -= 1
                else:
                    print('retry 3 times failed, stop the program')
                    exit(1)

    def close(self):
        self.ssh_client.close()

    def send(self, cmd):
        stdin, stdout, stderr = self.ssh_client.exec_command(cmd.strip())
        return stdout.read().decode('utf-8').strip(), stderr.read().decode('utf-8').strip()


class Seagull(object):
    def __init__(self, linux):
        self.linux = linux

    def send(self, protocol):
        client_cmd = SEAGULL_CLIENT_CMD.format(protocol, self.linux.ip)
        server_cmd = SEAGULL_SERVER_CMD.format(protocol, self.linux.ip)
        try:
            self.linux.connect()
            client_out, client_err = self.linux.send(client_cmd)
            server_out, server_err = self.linux.send(server_cmd)
            if (not client_err) or (not server_err):
                raise SeagullException(500, 'start seagull failed')
        except Exception as e1:
            print(e1)
            raise e1
        finally:
            self.linux.close()

    def download(self, protocol, mode='client'):
        """
        :param protocol:
        :param mode: client or server
        :return: 
        """
        try:
            self.linux.connect()
            if mode == 'client':
                file_cmd = SEAGULL_CLIENT_RESULT_FILE_CMD % (protocol, protocol)
                out, err = self.linux.send(file_cmd)
                filter_cmd = SEAGULL_CLIENT_RESULT_FILTER_CMD % (protocol, out)
            else:
                file_cmd = SEAGULL_SERVER_RESULT_FILE_CMD % (protocol, protocol)
                out, err = self.linux.send(file_cmd)
                filter_cmd = SEAGULL_SERVER_RESULT_FILTER_CMD % (protocol, out)
            out = self.linux.send(filter_cmd)
            return out[0].split(';') if out[0] else None
        except Exception as e1:
            print('download {0}:{1}:{2} failed'.format(self.linux.ip, protocol, mode))
        finally:
            self.linux.close()

    def dump(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/counters/all".format(self.linux.ip, control_port)
            return requests.get(url)
        except Exception as e1:
            print('dump' + url + ' failed')

    def set_rate(self, control_port, value):
        try:
            url = "http://{0}:{1}/seagull/command/rate?value={3}".format(self.linux.ip, control_port, value)
            requests.put(url)
        except Exception as e1:
            print('set_rate' + url + ' failed')

    def ramp(self, control_port, value, duration):
        try:
            url = "http://{0}:{1}/seagull/command/ramp?value={3}&duration={4}".format(self.linux.ip, control_port,
                                                                                      value, duration)
            requests.put(url)
        except Exception as e1:
            print('ramp' + url + ' failed')

    def stop(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/command/stop".format(self.linux.ip, control_port)
            requests.put(url)
        except Exception as e1:
            print('stop' + url + ' failed')

    def pause(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/command/pause".format(self.linux.ip, control_port)
            requests.put(url)
        except Exception as e1:
            print('pause' + url + ' failed')

    def burst(self, control_port):
        """
        only for client
        """
        try:
            url = "http://{0}:{1}/seagull/command/burst".format(self.linux.ip, control_port)
            requests.put(url)
        except Exception as e1:
            print('burst' + url + ' failed')


class SeagullTask(object):

    def __init__(self, protocol, conf, instrument):
        self.protocol = protocol
        self.conf = conf or {}
        self.instrument = instrument

    def set(self, vm_ips, test_caps, test_times):
        return {}

    def __check(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            client_rsp = seagull.dump(SEAGULL_CLIENT_DEFAULT_PORT)
            server_rsp = seagull.dump(SEAGULL_SERVER_DEFAULT_PORT)
            if client_rsp.status_code != 200 or server_rsp.status_code != 200:
                return vm_ip
        return

    def start(self, vm_ips):
        # 1、check vm status
        result = {'code': 200, 'message': 'ok'}
        check_ip = self.__check(vm_ips)
        if check_ip:
            result['code'] = 500
            result['data'] = check_ip
            return result

        # 2、start vm 
        rollback_vm_ips = []
        for vm_ip in vm_ips:
            try:
                seagull = Seagull(Linux(vm_ip, self.conf[vm_ip]['username'], self.conf[vm_ip]['password']))
                seagull.send(self.protocol)
            except SeagullException as e1:
                rollback_vm_ips.append(vm_ip)
                print(e1)

        # 3、rollback vm or return the execute result 
        if not rollback_vm_ips:
            self.stop(rollback_vm_ips)
            result['code'] = 500
            result['data'] = 'VM start failed'
            return result
        else:
            while True:
                seagull = Seagull(Linux(random.choice(vm_ips)))
                response = seagull.dump(random.choice([SEAGULL_CLIENT_DEFAULT_PORT, SEAGULL_SERVER_DEFAULT_PORT]))
                if response.status_code != 200:
                    break

            result['data'] = self.__download(vm_ips)
            return result

    def pause(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            seagull.pause(SEAGULL_CLIENT_DEFAULT_PORT)
            seagull.pause(SEAGULL_SERVER_DEFAULT_PORT)
        return

    def stop(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            seagull.stop(SEAGULL_CLIENT_DEFAULT_PORT)
            seagull.stop(SEAGULL_SERVER_DEFAULT_PORT)
        return

    def __download(self, vm_ips):
        result = {}
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip, self.conf[vm_ip]['username'], self.conf[vm_ip]['password']))
            seagull.download(self.protocol)
            # calc
        return result

    def dump(self, vm_ips):
        counters = {}
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            counters[vm_ip]['client'] = seagull.dump(SEAGULL_CLIENT_DEFAULT_PORT).text
            counters[vm_ip]['server'] = seagull.dump(SEAGULL_SERVER_DEFAULT_PORT).text
        return counters


if __name__ == '__main__':
    seagull = Seagull(Linux('192.168.245.136', 'cmcc', 'cmcc123'))
    print(seagull.download('diameter', 'client'))

    # parser = argparse.ArgumentParser(description="Seagull Task Controller",
    #                                  formatter_class=argparse.RawTextHelpFormatter)
    # parser.add_argument('--conf', action='store', dest='config_file_path', help='Configuration file path')
    # parser.add_argument('--vm-ips', nargs='+', action='store', dest='vm_ips', help='VM IPs for seagull')
    # parser.add_argument('--caps', nargs='+', action='store', dest='test_caps', help='Caps for seagull case')
    # parser.add_argument('--test-times', action='store', dest='test_times', help='Test times for seagull case')
    # parser.add_argument('--instrument', action='store', dest='instrument', help='Instrument address')
    # parser.add_argument('--protocol', action='store', dest='protocol', help='protocol for seagull case')
    # parser.add_argument('--mode', action='store', dest='mode', help='Supports 6 mode.' \
    #                                                                 '\nset - Set the instrument for seagull' \
    #                                                                 '\nstart - Start task' \
    #                                                                 '\npause - Pause task' \
    #                                                                 '\nstop - Stop task' \
    #                                                                 '\ndump - Dump real-time counters of each Seagull VM',
    #                     choices=('set', 'start', 'pause', 'stop', 'dump'))
    # parser.add_argument('--result-json', action='store', dest='result', help='Result json file.')
    # args = parser.parse_args()
    #
    # vm_ips = args.vm_ips
    # test_caps = args.test_caps
    # test_times = args.test_times
    # instrument = args.instrument
    # mode = args.mode if args.mode else 'dump'
    # protocol = args.protocol if args.protocol else 'diameter'
    # result_file = args.result if args.result else None
    #
    # conf = {}
    # with open(args.config_file_path) as json_file:
    #     json_conf = json.load(json_file)
    #
    # try:
    #     task = SeagullTask(protocol, conf, instrument)
    #     if mode == 'set':
    #         out = task.set(vm_ips, test_caps, test_times)
    #     elif mode == 'start':
    #         out = task.start(vm_ips)
    #     elif mode == 'pause':
    #         out = task.pause(vm_ips)
    #     elif mode == 'stop':
    #         out = task.stop(vm_ips)
    #     elif mode == 'dump':
    #         out = task.dump(vm_ips)
    #
    #     print('Done')
    # finally:
    #     seagull_result = json.dumps(out, default=lambda x: x.__dict__)
    #     print(seagull_result)
    #     if result_file:
    #         with open(result_file, "w+") as f:
    #             f.write(seagull_result)
