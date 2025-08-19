import ipdb

from jenkins_jinny.main import Build, search_build

for build in search_build("job/deploy-openstack-k8s/",
                          condition="MCP_PIPELINES_REFSPEC > a",
                          limit=100,
                          fmt="{url} {start_time} {parent}"):
    print(build)
    if build.has_log_line("TLS handshake"):
        print(f"=====> {build}")

# print("I completed looking jobs")