from datetime import datetime
from jenkins_jinny.main import Build, jobs_in_view

for build in jobs_in_view("https://mos-ci.infra.mirantis.net/view/MOSK 24.3 CI/", fmt=""):
    build: Build
    if build.server.get_queue_info().__len__() > 2:
        raise Exception("No more free slots to build. "
              "Queue in the Jenkins server is not empty")
    if build.is_in_queue():
        print("Build is already in queue")
        continue

    if build.number and build.start_time >= datetime(year=2024, month=8, day=27):
        print("Skipped because we have new build")
        continue

    print(f"I want to build {build} {build.url}")
    build.build()

print("I completed looking jobs")
