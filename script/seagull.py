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
import logging
import random
from time import sleep

import paramiko
import requests

SEAGULL_CLIENT_DEFAULT_PORT = 9000
SEAGULL_SERVER_DEFAULT_PORT = 9100

SEAGULL_HOME = '/opt/seagull/data'

SEAGULL_CLIENT_CMD = 'cd ' + SEAGULL_HOME + r'/{0}-env/run && sudo ./start_client.ksh {1}:' + str(SEAGULL_CLIENT_DEFAULT_PORT) + r' && ls'
SEAGULL_SERVER_CMD = 'cd ' + SEAGULL_HOME + r'/{0}-env/run && sudo ./start_server.ksh {1}:' + str(SEAGULL_SERVER_DEFAULT_PORT) + r' && ls'

SEAGULL_CLIENT_RESULT_FILE_CMD = "sudo ls -lt " + SEAGULL_HOME + r"/%s-env/logs | grep client-stat.%s | head -n 1 |awk '{print $9}'"
SEAGULL_CLIENT_RESULT_FILTER_CMD = "sudo cat " + SEAGULL_HOME + r"/%s-env/logs/%s | awk 'END {print}' | cut -d';' -f 5,11"

SEAGULL_SERVER_RESULT_FILE_CMD = "sudo ls -lt " + SEAGULL_HOME + r"/%s-env/logs | grep server-stat.%s | head -n 1 |awk '{print $9}'"
SEAGULL_SERVER_RESULT_FILTER_CMD = "sudo cat " + SEAGULL_HOME + r"/%s-env/logs/%s | awk 'END {print}' | cut -d';' -f 9"

SEAGULL_CLIENT_CONFIG_PORT_CMD = r"sudo sed 's/dest=.*\"/dest={0}\"/g' " + SEAGULL_HOME + r"/{1}-env/config/conf.client.xml"
SEAGULL_CLIENT_CONFIG_CAPS_CMD = r"sudo sed 's/name=\"call-rate\".*></name=\"call-rate\" value=\"{0}\"></g' " + SEAGULL_HOME + r"/{1}-env/config/conf.client.xml"
SEAGULL_SERVER_CONFIG_CALLS_CMD = r"sudo sed 's/name=\"number-calls\".*></name=\"number-calls\" value=\"{0}\"></g' " + SEAGULL_HOME + r"/{1}-env/config/conf.client.xml"

# fp = logging.FileHandler('a.txt', encoding='utf-8')   # 将日志记录到文件中
fs = logging.StreamHandler()  # 将日志输出到控制台
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%m/%d/%Y %H:%M:%S %p", handlers=[fs])


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

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(self)

    def connect(self):
        while True:
            try:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.ssh_client.connect(hostname=self.ip, username=self.username, password=self.password)
                logging.info("Successful connection->".format(self.ip))
                return
            except Exception as e1:
                if self.try_times != 0:
                    logging.error('connect %s failed，try to retry' % self.ip)
                    self.try_times -= 1
                else:
                    logging.error('retry 3 times failed, stop the program')
                    exit(1)

    def close(self):
        self.ssh_client.close()

    def send_invoke_shell_ack(self, cmd):
        self.connect()
        logging.info('send_invoke_shell_ack cmd: {0}'.format(cmd))
        try:
            result = ''
            remote_connect = self.ssh_client.invoke_shell()
            remote_connect.send(cmd + '\r')
            while True:
                sleep(0.5)
                result += remote_connect.recv(65535).decode('utf-8')
                return result
        except Exception as e1:
            logging.error('send_invoke_shell_ack cmd: {0} is error'.format(cmd), e1)
        finally:
            self.close()

    def send_ack(self, cmd):
        self.connect()
        logging.info('send_ack cmd: {0}'.format(cmd))
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd.strip())
            return stdout.read().decode('utf-8').strip(), stderr.read().decode('utf-8').strip()
        except Exception as e1:
            logging.error('send_ack cmd: {0} is error'.format(cmd), e1)
        finally:
            self.close()


class Seagull(object):
    def __init__(self, linux):
        self.linux = linux

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(self)

    def set_config(self, protocol, sut_address, caps, number_calls):
        try:
            self.linux.send_ack(SEAGULL_CLIENT_CONFIG_PORT_CMD.format(sut_address, protocol))
            self.linux.send_ack(SEAGULL_CLIENT_CONFIG_CAPS_CMD.format(caps, protocol))
            if number_calls:
                self.linux.send_ack(SEAGULL_SERVER_CONFIG_CALLS_CMD.format(number_calls, protocol))
        except Exception as e1:
            msg = 'set_config vm {0} failed'.format(self.linux.ip)
            logging.error(msg, e1)
            raise SeagullException(9999, msg)

    def start(self, protocol):
        try:
            self.linux.send_invoke_shell_ack(SEAGULL_SERVER_CMD.format(protocol, self.linux.ip))
            self.linux.send_invoke_shell_ack(SEAGULL_CLIENT_CMD.format(protocol, self.linux.ip))
        except Exception as e1:
            msg = 'start vm {0} failed'.format(self.linux.ip)
            logging.error(msg, e1)
            raise SeagullException(9999, msg)

    def download_client(self, protocol):
        try:
            out, err = self.linux.send_ack(SEAGULL_CLIENT_RESULT_FILE_CMD % protocol)
            out = self.linux.send_ack(SEAGULL_CLIENT_RESULT_FILTER_CMD % (protocol, out))
            return out[0].split(';') if out[0] else None
        except Exception as e1:
            logging.error('download_client {0}:{1} failed'.format(self.linux.ip, protocol), e1)
            return

    def download_server(self, protocol):
        try:
            out, err = self.linux.send_ack(SEAGULL_SERVER_RESULT_FILE_CMD % protocol)
            out = self.linux.send_ack(SEAGULL_SERVER_RESULT_FILTER_CMD % (protocol, out))
            return out[0].split(';') if out[0] else None
        except Exception as e1:
            logging.error('download_server {0}:{1} failed'.format(self.linux.ip, protocol), e1)
            return

    def status(self, control_port):
        try:
            url = "http://{0}:{1}/counters/all".format(self.linux.ip, control_port)
            rsp = requests.get(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('status {0} failed'.format(url), e1)
            return

    def dump(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/counters/all".format(self.linux.ip, control_port)
            rsp = requests.get(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('dump {0} failed'.format(url), e1)
            return

    def set_rate(self, control_port, value):
        try:
            url = "http://{0}:{1}/seagull/command/rate?value={3}".format(self.linux.ip, control_port, value)
            rsp = requests.put(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('set_rate {0} failed'.format(url), e1)
            return

    def ramp(self, control_port, value, duration):
        try:
            url = "http://{0}:{1}/seagull/command/ramp?value={3}&duration={4}".format(self.linux.ip, control_port,
                                                                                      value, duration)
            rsp = requests.put(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('ramp {0} failed'.format(url), e1)
            return

    def stop(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/command/stop".format(self.linux.ip, control_port)
            rsp = requests.put(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('stop {0} failed'.format(url), e1)
            return

    def pause(self, control_port):
        try:
            url = "http://{0}:{1}/seagull/command/pause".format(self.linux.ip, control_port)
            rsp = requests.put(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('pause {0} failed'.format(url), e1)
            return

    def burst(self, control_port):
        """
        only for client
        """
        try:
            url = "http://{0}:{1}/seagull/command/burst".format(self.linux.ip, control_port)
            rsp = requests.put(url)
            return rsp.status_code, rsp.text
        except Exception as e1:
            logging.error('burst {0} failed'.format(url), e1)
            return


class SeagullTask(object):
    def __init__(self, protocol, conf, sut_address, caps, number_calls):
        self.protocol = protocol
        self.conf = conf or {}
        self.sut_address = sut_address
        self.caps = caps
        self.number_calls = number_calls

    def start(self, vm_ips):
        # 1、check vm status
        self.__check(vm_ips)

        # 2、set vm config
        self.__set_config(vm_ips)

        # 3、start vm
        started_vm_ips = []
        for vm_ip in vm_ips:
            try:
                seagull = Seagull(Linux(vm_ip, self.conf[vm_ip]['username'], self.conf[vm_ip]['password']))
                seagull.start(self.protocol)
            except SeagullException as e1:
                started_vm_ips.append(vm_ip)
                logging.error('VM {0} start failed'.format(vm_ip), e1)
                break

        # 4、rollback vm or return the execute result
        if started_vm_ips:
            self.stop(started_vm_ips)
            msg = 'Rollback vms {0}'.format(started_vm_ips)
            logging.error(msg)
            raise SeagullException(9999, msg)
        else:
            # wait the seagull stop, if anyone is stop then exit the while
            while True:
                try:
                    sleep(2)
                    logging.info('Check seagull status every 5 seconds')
                    seagull = Seagull(Linux(random.choice(vm_ips)))
                    rsp = seagull.status(random.choice([SEAGULL_CLIENT_DEFAULT_PORT, SEAGULL_SERVER_DEFAULT_PORT]))
                    if not rsp:
                        break
                except Exception as e1:
                    logging.error('Seagull vms is stoped', e1)
                    break

        return self.__download(vm_ips)

    def pause(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            seagull.pause(SEAGULL_CLIENT_DEFAULT_PORT)
            seagull.pause(SEAGULL_SERVER_DEFAULT_PORT)
        return "Success"

    def stop(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            seagull.stop(SEAGULL_CLIENT_DEFAULT_PORT)
            seagull.stop(SEAGULL_SERVER_DEFAULT_PORT)
        return "Success"

    def dump(self, vm_ips):
        counters = {}
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))

            counter = {'client': None, 'server': None}
            client_rsp = seagull.dump(SEAGULL_CLIENT_DEFAULT_PORT)
            counter['client'] = client_rsp[1].replace('\r\n', ',') if client_rsp and client_rsp[0] == 200 else None
            server_rsp = seagull.dump(SEAGULL_SERVER_DEFAULT_PORT)
            counter['server'] = server_rsp[1].replace('\r\n', ',') if server_rsp and server_rsp[0] == 200 else None

            counters[vm_ip] = counter
        return counters

    def __download(self, vm_ips):
        result = {'client': {'elapsed_time': None, 'outgoing_calls': 0},
                  'server': {'incoming_calls': 0},
                  'failed_calls': 0}
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip, self.conf[vm_ip]['username'], self.conf[vm_ip]['password']))
            out_client = seagull.download_client(self.protocol)
            if out_client:
                # result['client']['call_rate'] += out_client[0]
                result['client']['elapsed_time'] = out_client[0]
                result['client']['outgoing_calls'] += int(out_client[1])

            out_server = seagull.download_server(self.protocol)
            if out_server:
                result['server']['incoming_calls'] += int(out_server[0])

            result['failed_calls'] += (result['client']['outgoing_calls'] - result['server']['incoming_calls'])
        return result

    def __set_config(self, vm_ips):
        for vm_ip, cap in zip(vm_ips, self.caps):
            seagull = Seagull(Linux(vm_ip, self.conf[vm_ip]['username'], self.conf[vm_ip]['password']))
            seagull.set_config(self.protocol, self.sut_address, self.caps, self.number_calls)

    def __check(self, vm_ips):
        for vm_ip in vm_ips:
            seagull = Seagull(Linux(vm_ip))
            client_rsp = seagull.status(SEAGULL_CLIENT_DEFAULT_PORT)
            server_rsp = seagull.status(SEAGULL_SERVER_DEFAULT_PORT)
            if client_rsp or server_rsp:
                msg = 'VM {0} is running'.format(vm_ip)
                logging.error(msg)
                raise SeagullException(9999, msg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Seagull Task Controller",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--conf', action='store', dest='config_file_path', help='Configuration file path')
    parser.add_argument('--instrument-ips', action='store', dest='instrument_ips', help='Instrument VM IPs for seagull')
    parser.add_argument('--caps', action='store', dest='caps', help='Call rate of seagull case')
    parser.add_argument('--number-calls', action='store', dest='number_calls', help='Number-calls of seagull case')
    parser.add_argument('--sutaddress', action='store', dest='sut_address', help='Sut address for DRA')
    parser.add_argument('--protocol', action='store', dest='protocol', help='Protocol for seagull case')
    parser.add_argument('--mode', action='store', dest='mode', help='Supports 5 mode.' \
                                                                    '\nstart - Start task' \
                                                                    '\npause - Pause task' \
                                                                    '\nstop - Stop task' \
                                                                    '\ndump - Dump real-time counters of each Seagull VM',
                        choices=('start', 'pause', 'stop', 'dump'))
    parser.add_argument('--result-json', action='store', dest='result', help='Result json file.')
    args = parser.parse_args()


    def _check_parameters():
        if number_calls < 1000:
            raise SeagullException(9999, 'number_calls must over 1000')

        for vm_ip, cap in zip(vm_ips, caps):
            if not vm_ip or not cap:
                raise SeagullException(9999, "vm {0} cap {1} is empty".format(vm_ip, cap))


    vm_ips = args.instrument_ips.split(';') if args.instrument_ips else []
    caps = args.caps.split(';') if args.caps else []
    number_calls = args.number_calls
    sut_address = args.sut_address
    mode = args.mode if args.mode else 'dump'
    protocol = args.protocol if args.protocol else 'diameter'
    result_file = args.result if args.result else None

    _check_parameters()

    conf = {}
    with open(args.config_file_path) as json_file:
        json_conf = json.load(json_file)
        for ip_account in json_conf['instrument']:
            instrument_mgs = ip_account['instrument_mgs']
            account = {'username': instrument_mgs['username'], 'password': instrument_mgs['password']}
            conf[instrument_mgs['address']] = account

    output = {}
    try:
        task = SeagullTask(protocol, conf, sut_address, caps, number_calls)
        if mode == 'start':
            output['data'] = task.start(vm_ips)
        elif mode == 'pause':
            output['data'] = task.pause(vm_ips)
        elif mode == 'stop':
            output['data'] = task.stop(vm_ips)
        elif mode == 'dump':
            output['data'] = task.dump(vm_ips)

        print('Done')
    finally:
        seagull_result = json.dumps(output, default=lambda x: x.__dict__)
        print(seagull_result)
        if result_file:
            with open(result_file, "w+") as f:
                f.write(seagull_result)
