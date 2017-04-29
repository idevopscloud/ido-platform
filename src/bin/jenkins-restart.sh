#!/bin/bash
export PATH=/sbin:/usr/sbin:/usr/local/sbin:/usr/local/bin:/usr/bin:/bin

wait_for_service_ready()
{
  attempt=0
  while true; do
        rsp_code=$(curl -o /dev/null -s -m 10 --connect-timeout 10 -w %{http_code} http://localhost:28080/login)
    if [[ ${rsp_code} != "200" ]]; then
      if (( attempt > 10 )); then
        echo "failed to start Jenkins."
        exit 1
      fi
    else
        echo "Attempt $(($attempt+1)): Jenkins is ready."
      break
    fi
    echo "Attempt $(($attempt+1)): Jenkins not ready yet."
    attempt=$(($attempt+1))
    sleep 5
  done
}

import_job()
{
  local job_name=$1
  attempt=0
  cmd=create-job
  if [ -f "${data_dir}/jobs/${job_name}/config.xml" ]; then
      cmd=update-job
  fi

  while true; do
    docker exec -it $container_name \
        bash -c "java -jar /var/jenkins_home/war/WEB-INF/jenkins-cli.jar -s http://localhost:8080 ${cmd} ${job_name} < /tmp/${job_name}_config.xml"
    local ret=$?
    if [[ ${ret} != 0 ]]; then
      if (( attempt > 10 )); then
        echo "failed to import job."
        exit 1
      fi
    else
        echo "Attempt $(($attempt+1)): import job OK"
      break
    fi
    echo "Attempt $(($attempt+1)): failed to import job."
    attempt=$(($attempt+1))
    sleep 5
  done
}

jenk_config(){
    docker exec -it $container_name \
        bash -c "cp /tmp/config.xml /var/jenkins_home && curl http://localhost:8080/reload -X POST"
}

ido_registry_login(){
    docker exec -it ${container_name} \
        bash -c 'sudo docker login -u read_only -p "d[4|_Gj]jKx:JG" -e cd@idevopscloud.com index.idevopscloud.com:5000'
}

OPTS=`getopt -o "h" -l data-dir: -l hosts: -l image: -- "$@"`
if [ $? != 0 ]; then
    echo "Usage error"
    exit 1
fi
eval set -- "$OPTS"

container_name='platform-jenkins'
data_dir=""
image=""

while true ; do
    case "$1" in
        --data-dir) data_dir=$2; shift 2;; 
        --image) image=$2; shift 2;;
        --) shift; break;;
    esac
done

if [ "$data_dir" == "" -o "$image" == "" ]; then
    echo "--data-dir and --image options must be specified"
    exit 1
fi

mkdir -p ${data_dir}
chmod 777 -R ${data_dir}

docker pull $image > /etc/null
docker rm -vf $container_name
docker run -d \
    -v ${data_dir}:/var/jenkins_home \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v $(which docker):/usr/bin/docker \
    -v /lib/x86_64-linux-gnu/libapparmor.so.1:/lib/x86_64-linux-gnu/libapparmor.so.1:ro \
    -e JAVA_OPTS=" -Xmx512m -Xms512m -Xmn219m " \
    -m 1400m \
    -p 28080:8080 --name=${container_name} ${image}

wait_for_service_ready
import_job base_img
import_job comp_img
jenk_config
ido_registry_login
