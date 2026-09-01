from os import environ as os_env

JENKINS_USER = os_env.get("JENKINS_USER")
JENKINS_PASSWORD = os_env.get("JENKINS_PASSWORD")

RETRY_TOTAL = os_env.get("RETRY_TOTAL", 15)
RETRY_CONNECT = os_env.get("RETRY_CONNECT", 15)
RETRY_READ = os_env.get("RETRY_READ", 15)
RETRY_BACKOFF_FACTOR = os_env.get("RETRY_BACKOFF_FACTOR", 2)
