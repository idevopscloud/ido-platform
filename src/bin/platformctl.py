#!/usr/bin/env python

import sys
import os
import subprocess
import json
import time
import base64
import argparse
import urllib2
import zipfile
import MySQLdb

PLATFORM_ROOT = '/opt/ido/platform'
CONFIG_FILE = '/etc/ido/platform.json'
DOCKER = '/opt/ido/platform/bin/docker'
PLATFORM_VERSION = '1.0.0'
DOCKER_REGISTRY = 'index.idevopscloud.com:5000'
IMAGE_VERSIONS = {
    'redis': '2.8',
    'account': '1.0.1',
    'app': '1.0.1',
    'core': '1.0.1',
    'registry': '1.0.1',
    'web': '1.0.1.1',
    'jenkins': '1.0.1',
    'cdapi': '1.0.1',
}

def kill_process_by_name(name):
    fobj = file('/dev/null')
    child = subprocess.Popen('killall {}'.format(name).split(), stdout=fobj, stderr=fobj)
    child.wait()

def is_docker_ok():
    fobj = file('/dev/null')
    child = subprocess.Popen('/opt/ido/platform/bin/docker info'.split(), stdout=fobj, stderr=fobj)
    status = child.wait()
    if status == 0:
        return True
    else:
        return False

def is_image_existed(image_name, image_tag):
    cmdline = [
        'bash',
        '-c',
        'docker images | grep {}'.format(image_name) + ' | awk \'{print $1,$2;}\''
    ]
    child = subprocess.Popen(cmdline, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child.wait()
    lines = child.stdout.readlines()
    if len(lines) == 0:
        return False

    for line in lines:
        (name, tag) = line.split(' ')
        if tag == image_tag:
            return True

    return True

def pull_image(image_name, tag):
    if not is_image_existed(image_name, tag):
        os.system('docker pull ' + '{}:{}'.format(image_name, tag))

def start_docker():
    def is_docker_running():
        fobj = file('/dev/null')
        child = subprocess.Popen('docker info'.split(), stdout=fobj, stderr=fobj)
        status = child.wait()
        if status == 0:
            return True
        else:
            return False

    if is_docker_running():
        return

    print 'starting docker'
    kill_process_by_name('docker')
    os.system('bash -c \"ip link del docker0 2>&1\n" >/dev/null')
    cmdline = '/opt/ido/platform/bin/docker -d --storage-driver=aufs --insecure-registry=index.idevopscloud.com:5000'
    docker_log_fobj = file('/var/log/ido/docker.log', 'a')
    child = subprocess.Popen(cmdline.split(), stdout=docker_log_fobj, stderr=docker_log_fobj)
    while child.poll() is None:
        if is_docker_ok():
            print 'docker started successfully'
            return True
        else:
            time.sleep(1)
    return False

def restart_container(container_name, image, volumns=None, ports=None, env_vars=None):
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/null'.format(DOCKER, container_name))
    cmdline = [ 
        DOCKER,
        'run',
        '-d',
        '--restart=always',
        '--name={}'.format(container_name)
    ]   
    if env_vars is not None:
        for key, value in env_vars.items():
            cmdline += ['-e', '{}={}'.format(key, value)]
    if ports is not None:
        for item in ports:
            cmdline += ['-p', item]
    if volumns is not None:
        for volumn in volumns:
            cmdline += ['-v', volumn]

    cmdline.append(image)

    child = subprocess.Popen(cmdline, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        return False

    return True

class PlatformConfig:
    def __init__(self):
        try:
            fobj = file(CONFIG_FILE)
            params = json.loads(fobj.read())
        except:
            raise

        self.host = params.get('host', None)
        if self.host is None:
            raise Exception('host is not specified')
        self.master_host = params.get('master_host', None)
        if self.master_host is None:
            raise Exception('master_host is not specified')
        self.data_dir = params.get('data_dir', None)
        self.mysql_host = params.get('mysql_host', None)
        self.mysql_port = params.get('mysql_port', None)
        self.mysql_user = params.get('mysql_user', None)
        self.mysql_password = params.get('mysql_password', None)
        self.paas_api_endpoint = 'http://{}:12306/api/v1'.format(self.master_host)
        self.kubernetes_master = params.get('kubernetes_master', None)
        self.service_port_min = params.get('service_port_min', None)
        self.service_port_max = params.get('service_port_max', None)
        self.redis_port = params['components']['redis']['port']
        self.account_port = params['components']['account']['port']
        self.account_db_name = params['components']['account']['db_name']
        self.core_port = params['components']['core']['port']
        self.core_db_name = params['components']['core']['db_name']
        self.application_port = params['components']['application']['port']
        self.application_db_name = params['components']['application']['db_name']
        self.web_port = params['components']['web']['port']
        self.registry_port = params['components']['registry']['port']
        self.registry_db_name = params['components']['registry']['db_name']
        self.jenkins_port = params['components']['jenkins']['port']
        self.cdapi_port = params['components']['cdapi']['port']
        self.public_address = params['public_address']

        try:
            self.__create_database()
        except:
            raise

    def __create_database(self):
        def is_database_existed(cursor, dbname):
            cursor.execute('SHOW DATABASES LIKE \'{}\''.format(dbname))
            result = cursor.fetchone()
            if result is not None and len(result) > 0:
                return True
            else:
                return False

        def is_table_existed(cursor, dbname, tablename):
            cursor.execute('select * from information_schema.tables where table_schema=\'{}\' AND table_name=\'{}\' limit 1'.format(dbname, tablename))
            result = cursor.fetchone()
            if result is not None and len(result) > 1:
                return True
            else:
                return False

        dbconn = MySQLdb.connect(host=self.mysql_host,
                                 user=self.mysql_user,
                                 passwd=self.mysql_password,
                                 port=self.mysql_port)
        cursor = dbconn.cursor()
        database_names = [
            self.account_db_name,
            self.core_db_name,
            self.application_db_name,
            self.registry_db_name,
        ]

        for database_name in database_names:
            if not is_database_existed(cursor, database_name):
                cursor.execute("create database IF NOT EXISTS {}".format(database_name))

        if (not is_table_existed(cursor, self.application_db_name, 'idevops_repos')) or not is_table_existed(cursor, self.application_db_name, 'idevops_repo_tags'):
            with zipfile.ZipFile('{}/conf/repo'.format(PLATFORM_ROOT), 'r') as z:
                z.extract('repo.sql', '/tmp', base64.b64encode('893091823'))
                subprocess.call(['bash', '-c', 'mysql -h{} -u{} -p{} {} < /tmp/repo.sql'.format(self.mysql_host, self.mysql_user, self.mysql_password, self.application_db_name)],
                                stdout=file('/dev/null'), stderr=file('/dev/null'))

def start_redis(platform_config):
    print 'starting redis'
    container_name = 'platform-redis'
    image_name = '{}/idevops/redis'.format(DOCKER_REGISTRY)
    image = '{}:{}'.format(image_name, IMAGE_VERSIONS['redis'])
    pull_image(image_name, IMAGE_VERSIONS['redis'])
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always -v {data_dir}/platform/redis:/data '\
              '-p {port}:6379 '\
              '--name {container_name} ' \
              '{image}' \
              .format(docker=DOCKER,
                      data_dir=platform_config.data_dir,
                      port=platform_config.redis_port,
                      container_name=container_name,
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start redis'
        return False

    print 'Redis started successfully'
    return True

def start_docker_registry():
    container_name = 'idevops-docker-registry'
    image_name = DOCKER_REGISTRY + '/idevops/registry'
    tag = '2.5.1'
    image = '{}:{}'.format(image_name, tag)
    pull_image(image_name, tag)
    restart_container(container_name, image, volumns=None, ports=['5000:5000'], env_vars=None)

def start_account(platform_config):
    print 'starting account'
    container_name = 'platform-account'
    image_name = '{}/idevops/account_management'.format(DOCKER_REGISTRY)
    image = '{}/idevops/account_management:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['account'])
    pull_image(image_name, IMAGE_VERSIONS['account'])
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always -v {data_dir}/platform/account_management:/mnt/account_management '\
              '-p {port}:80 '\
              '--name {container_name} ' \
              '-e DB_HOST={db_host} ' \
              '-e DB_USERNAME={db_user} ' \
              '-e DB_PASSWORD={db_password} ' \
              '-e DB_DATABASE={db_database} ' \
              '-e REDIS_HOST={redis_host} ' \
              '-e REDIS_SEVICE_PORT={redis_port} ' \
              '-e API_HOST={api_host}:{api_port} ' \
              '-e APP_DEBUG=false ' \
              '{image}' \
              .format(docker=DOCKER,
                      data_dir=platform_config.data_dir,
                      port=platform_config.account_port,
                      registry=DOCKER_REGISTRY,
                      account_version=IMAGE_VERSIONS['account'],
                      container_name=container_name,
                      db_host=platform_config.mysql_host,
                      db_user=platform_config.mysql_user,
                      db_password=platform_config.mysql_password,
                      db_database=platform_config.account_db_name,
                      redis_host=platform_config.host,
                      redis_port=platform_config.redis_port,
                      api_host=platform_config.host,
                      api_port=platform_config.core_port,
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start account'
        return False

    print 'Account started successfully'
    return True

def start_app(platform_config):
    print 'starting app'
    container_name = 'platform-app'
    image = '{}/idevops/application_management:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['app'])
    image_name = DOCKER_REGISTRY + '/idevops/application_management'
    pull_image(image_name, IMAGE_VERSIONS['app'])
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always -v {data_dir}/platform/application_management:/mnt/application_management '\
              '-p {port}:80 '\
              '--name {container_name} ' \
              '-e DB_HOST={db_host} ' \
              '-e DB_USERNAME={db_user} ' \
              '-e DB_PASSWORD={db_password} ' \
              '-e DB_DATABASE={db_database} ' \
              '-e REDIS_HOST={redis_host} ' \
              '-e REDIS_SERVICE_PORT={redis_port} ' \
              '-e API_HOST={api_host}:{api_port} ' \
              '-e PAAS_API_URL={paas_api_endpoint} ' \
              '-e K8S_END_POINT={kubernetes_master} ' \
              '{image}' \
              .format(docker=DOCKER,
                      data_dir=platform_config.data_dir,
                      port=platform_config.application_port,
                      container_name=container_name,
                      db_host=platform_config.mysql_host,
                      db_user=platform_config.mysql_user,
                      db_password=platform_config.mysql_password,
                      db_database=platform_config.application_db_name,
                      redis_host=platform_config.host,
                      redis_port=platform_config.redis_port,
                      api_host=platform_config.host,
                      api_port=platform_config.core_port,
                      paas_api_endpoint=platform_config.paas_api_endpoint,
                      kubernetes_master='http://{}:8080'.format(platform_config.master_host),
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start app'
        return False

    print 'App started successfully'

def start_core(platform_config):
    print 'starting core'
    container_name = 'platform-core'
    image = '{}/idevops/platform_core:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['core'])
    image_name = DOCKER_REGISTRY + '/idevops/platform_core'
    pull_image(image_name, IMAGE_VERSIONS['core'])
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always -v {data_dir}/platform/platform_core/storage:/mnt/storage '\
              '-p {port}:80 '\
              '--name {container_name} ' \
              '-e APP_OPS_HOST={app_ops_host} ' \
              '-e APP_BASE_URL={app_base_url} ' \
              '-e MYSQL_HOST={mysql_host} ' \
              '-e MYSQL_USER={mysql_user} ' \
              '-e MYSQL_PASSWORD={mysql_password} ' \
              '-e MYSQL_PREFIX=ops_ ' \
              '-e REDIS_HOST={redis_host} ' \
              '-e REDIS_port={redis_port} ' \
              '-e MYSQL_DB_NAME={mysql_db_name} ' \
              ' -e ACCOUNT_PORT={account_port}' \
              ' -e APP_PORT={app_port}'\
              ' -e REGISTRY_PORT={registry_port}'\
              ' -e API_HOST={api_host}'\
              ' {image}' \
              .format(docker=DOCKER,
                      data_dir=platform_config.data_dir,
                      port=platform_config.core_port,
                      container_name=container_name,
                      app_ops_host='http://{}:{}'.format(platform_config.host, platform_config.core_port),
                      app_base_url='http://{}:{}'.format(platform_config.host, platform_config.core_port),
                      mysql_host=platform_config.mysql_host,
                      mysql_user=platform_config.mysql_user,
                      mysql_password=platform_config.mysql_password,
                      redis_host=platform_config.host,
                      redis_port=platform_config.redis_port,
                      mysql_db_name=platform_config.core_db_name,
                      account_port=platform_config.account_port,
                      app_port=platform_config.application_port,
                      registry_port=platform_config.registry_port,
                      api_host=platform_config.host,
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start core'
        return False

    print 'Core started successfully'

def start_web(platform_config):
    print 'starting web'
    container_name = 'platform-web'
    image = '{}/idevops/platform_frontend:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['web'])
    image_name = DOCKER_REGISTRY + '/idevops/platform_frontend'
    pull_image(image_name, IMAGE_VERSIONS['web'])
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always '\
              '-p {port}:80 '\
              '--name {container_name} ' \
              '-e API_PORT={api_port} ' \
              '-e API_HOST={api_host} ' \
              '-e APP_HOST={app_host} ' \
              '-e SERVICE_PORT_MIN={service_port_min} ' \
              '-e SERVICE_PORT_MAX={service_port_max} ' \
              '-e REGISTRY_HOST={registry_host} ' \
              '{image}' \
              .format(docker=DOCKER,
                      data_dir=platform_config.data_dir,
                      port=platform_config.web_port,
                      container_name=container_name,
                      api_port=platform_config.core_port,
                      api_host=platform_config.public_address,
                      app_host='{}:{}'.format(platform_config.public_address, platform_config.application_port),
                      service_port_min=platform_config.service_port_min,
                      service_port_max=platform_config.service_port_max,
                      registry_host='{}:{}'.format(platform_config.public_address, platform_config.registry_port),
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start web'
        return False

    print 'Web started successfully'

def start_platform_registry(platform_config):
    print 'starting registry'
    container_name = 'platform-registry'
    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/null'.format(DOCKER, container_name))
    image = '{}/idevops/platform_registry:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['registry'])
    image_name = DOCKER_REGISTRY + '/idevops/platform_registry'
    pull_image(image_name, IMAGE_VERSIONS['registry'])

    cmdline = '{docker} run -d --restart=always '\
              '-p {port}:80 '\
              ' -v {data_dir}/platform/platform_registry:/mnt/platform_registry' \
              ' --name {container_name} ' \
              '-e APP_DEBUG=false ' \
              '-e DB_HOST={db_host} ' \
              '-e DB_PORT={db_port} ' \
              '-e DB_USERNAME={db_username} ' \
              '-e DB_PASSWORD={db_password} ' \
              '-e REDIS_HOST={redis_host} ' \
              '-e REDIS_PORT={redis_port} ' \
              '-e API_HOST={api_host}:{api_port} ' \
              '-e DB_DATABASE={db_database} ' \
              ' -e CD_HOST={cd_host}' \
              ' -e CD_USER=idevops' \
              ' -e CD_PWD=1f2d3a1f5d' \
              ' -e REGISTRY_HOST={registry_host}' \
              ' -e REGISTRY_PAAS_API_URL={paas_api}' \
              ' {image}' \
              .format(docker=DOCKER,
                      port=platform_config.registry_port,
                      data_dir=platform_config.data_dir,
                      container_name=container_name,
                      db_host=platform_config.host,
                      db_port=platform_config.mysql_port,
                      db_username=platform_config.mysql_user,
                      db_password=platform_config.mysql_password,
                      redis_host = platform_config.host,
                      redis_port = platform_config.redis_port,
                      api_host = platform_config.host,
                      api_port = platform_config.core_port,
                      db_database = platform_config.registry_db_name,
                      registry_host='{}:{}'.format(platform_config.host, 5000),
                      paas_api='http://{}:{}'.format(platform_config.master_host, 12306),
                      cd_host='{}:{}'.format(platform_config.host, platform_config.cdapi_port),
                      image=image)
    child = subprocess.Popen(cmdline.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start registry'
        return False

    print 'Registry started successfully'

def start_jenkins(platform_config):
    print 'Starting jenkins'
    os.system('bash {platform_root}/bin/jenkins-restart.sh --image={registry}/idevops/platform-jenkins:{tag} --data-dir={data_dir}' \
              .format(registry = DOCKER_REGISTRY,
                      platform_root=PLATFORM_ROOT,
                      tag = IMAGE_VERSIONS['jenkins'],
                      data_dir = platform_config.data_dir))
    print 'Jenkins started successfully'
    pass

def start_cdapi(platform_config):
    print 'starting cdapi'
    container_name = 'platform-cdapi'
    image = '{}/idevops/cd-api:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['cdapi'])
    image_name = DOCKER_REGISTRY + '/idevops/cd-api'
    pull_image(image_name, IMAGE_VERSIONS['cdapi'])

    os.system('bash -c \"{} rm -f {} 2>&1\">/dev/None'.format(DOCKER, container_name))
    cmdline = '{docker} run -d --restart=always ' \
              ' --name {container_name} ' \
              ' -e jenkins_addr=http://{jenkins_addr}' \
              ' -p {port}:23006' \
              ' {image}' \
              .format(docker=DOCKER,
                      port=platform_config.cdapi_port,
                      jenkins_addr='{}:{}'.format(platform_config.host, 28080),
                      container_name=container_name,
                      image=image)
    cmdline_list = cmdline.split()
    child = subprocess.Popen(cmdline_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if child.wait() != 0:
        print child.stderr.read()
        print 'Failed to start cdapi'
        return False

    print 'Cdapi started successfully'
    return True

def start_cd(platform_config):
    start_jenkins(platform_config)
    start_cdapi(platform_config)

def start_paas_agent(platform_config):
    def create_agent_config_file(platform_config):
        agent_config_file = '/etc/ido/paas-agent.json'
        file_obj = file(agent_config_file, "w")
        agent_config = {
            "docker": {
                "http": None,
                "telnet": None,
                "proc": True
            },
            "platform_core": {
                "http": "{}:{}/api/token".format(platform_config.host, platform_config.core_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.core_port),
                "proc": False
            },
            "platform_frontend": {
                "http": "{}:{}".format(platform_config.host, platform_config.web_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.web_port),
                "proc": False
            },
            "account_management": {
                "http": "{}:{}".format(platform_config.host, platform_config.account_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.account_port),
                "proc": False
            },
            "application_management": {
                "http": "{}:{}".format(platform_config.host, platform_config.application_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.application_port),
                "proc": False
            },
            "registry": {
                "http": "{}:{}".format(platform_config.host, platform_config.registry_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.registry_port),
                "proc": False
            },
            "cd-api": {
                "http": "{}:{}/ping".format(platform_config.host, platform_config.cdapi_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.cdapi_port),
                "proc": False
            },
            "platform-jenkins": {
                "http": "{}:{}".format(platform_config.host, platform_config.jenkins_port),
                "telnet": "{}:{}".format(platform_config.host, platform_config.jenkins_port),
                "proc": False
            },
            "mysql": {
                "http": None,
                "telnet": "{}:{}".format(platform_config.host, platform_config.mysql_port),
                "proc": False
            },
            "redis": {
                "http": None,
                "telnet": "{}:{}".format(platform_config.host, platform_config.redis_port),
                "proc": False
            }
        }
        json.dump(agent_config, file_obj, indent=2)
        file_obj.close()

    create_agent_config_file(platform_config)

    image = '{}/idevops/paas-agent:{}'.format(DOCKER_REGISTRY, IMAGE_VERSIONS['paas-agent'])
    volumns = [
        '/proc:/host/proc:ro',
        '/sys:/host/sys:ro',
        '/:/rootfs:ro',
        '/etc/ido/paas-agent.json:/ido/paas-agent/conf/platform.json'
    ]
    ports = [
        '22305:12305'
    ]
    restart_container('paas-agent', image, volumns=volumns, ports=ports, env_vars=None)

def start_all(platform_config):
    start_docker()
    start_docker_registry()
    start_redis(platform_config)
    start_account(platform_config)
    start_app(platform_config)
    start_core(platform_config)
    start_web(platform_config)
    start_platform_registry(platform_config)
    start_cd(platform_config)

def cmd_start(args):
    try:
        platform_config = PlatformConfig()
    except Exception as e:
        print str(e)
        print 'Failed to start ido-platform'
        return

    if args.component == 'redis':
        start_redis(platform_config)
    elif args.component == 'account':
        start_account(platform_config)
    elif args.component == 'app':
        start_app(platform_config)
    elif args.component == 'core':
        start_core(platform_config)
    elif args.component == 'web':
        start_web(platform_config)
    elif args.component == 'registry':
        start_registry(platform_config)
    elif args.component == 'paas-agent':
        start_paas_agent(platform_config)
    elif args.component == 'cd':
        start_cd(platform_config)
    elif args.component == 'docker':
        start_docker()
    elif args.component == 'docker-registry':
        start_docker_registry()
    elif args.component == 'all':
        start_all(platform_config)

def help(args):
    print 'help command here'

def cmd_version(args):
    print PLATFORM_VERSION

def main(environ, argv):
    parser = argparse.ArgumentParser(prog='platformctl')
    subparsers = parser.add_subparsers(help='sub-command help')

    parser_start = subparsers.add_parser('start')
    parser_start.add_argument('component', choices=['all', 'redis', 'account','app', 'core', 'registry', 'web', 'cd', 'paas-agent', 'docker', 'docker-registry'])
    parser_start.set_defaults(func=cmd_start)

    parser_version = subparsers.add_parser('version')
    parser_version.set_defaults(func=cmd_version)

    args = parser.parse_args(sys.argv[1:])
    return (args.func(args))

if __name__ == '__main__':
    main(os.environ, sys.argv[1:])

