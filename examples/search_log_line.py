import ipdb

from jenkins_jinny.main import Build, search_build

for build in search_build("https://mos-ci.infra.mirantis.net/job/deploy-openstack-k8s/74110",
                          condition="MCP_PIPELINES_REFSPEC > a",
                          limit=300,
                          fmt=""):
    # ipdb.set_trace()
    if build.has_log_line("TLS handshake"):
        print(f"=====> {build}")

print("I completed looking jobs")