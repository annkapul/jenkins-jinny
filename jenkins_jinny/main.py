import enum
import os
import sys

import jenkins
import jmespath
import requests
import logging
from parse import parse
import networkx as nx
import ipdb
import pathlib
import datetime
import operator
from typing import List, Optional
import functools

from requests.adapters import HTTPAdapter
from urllib3 import Retry

from .exceptions import BuildNotFoundException
import jenkins_jinny.config as config
import urllib.parse
import re


level = logging.DEBUG if os.environ.get("DEBUG") else logging.INFO

logging.basicConfig(level=level, stream=sys.stdout,
                    format="%(asctime)s - %(name)s - %(levelname)s- %(funcName)s - %(message)s")
LOG = logging.getLogger(__name__)

retry = Retry(
    total=15,
    connect=15,
    read=15,
    backoff_factor=2,  # 2s, 4s, 8s, ... capped at 120s
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"HEAD", "GET", "PUT", "POST", "PATCH", "DELETE", "OPTIONS", "TRACE"}),
)

class Params:
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def __getattr__(self, name):
        # Do not throw Attribute error if object doesn't have an attribute
        # with 'name'
        return None

    def __repr__(self):
        return " ".join(f"{k}={v}" for k, v in self.__dict__.items())


class LastBuildLinks(str, enum.Enum):
    LAST_BUILD = 'lastBuild'
    LAST_COMPLETED = "lastCompletedBuild"
    LAST_FAILED = "lastFailedBuild"
    LAST_SUCCESSFUL = "lastSuccessfulBuild"
    LAST_UNSUCCESSFUL = "lastUnsuccessfulBuild"


class Build:
    _fmt: Optional[str] = None
    def __init__(self,
                 url=None,
                 job_name=None,
                 build_number=None,
                 server=None,
                 last_build_link=LastBuildLinks.LAST_BUILD,
                 fmt=None,
                 http_adapter: Optional[HTTPAdapter]=None):
        """
        :param url: full url address of job. It will be parsed into server,
        job_name, build_number

        :param job_name: name of job (without jenkins url anf view's name)

        :param build_number: int , number of the build. Returns latest build
        if not defined

        :param server: str with url of Jenkins server or jenkins.Jenkins object
        """
        self.__crumb = None
        self._parent = None
        self._heirs = None
        self._children = list()
        self._fmt = None
        if fmt:
            setattr(Build, '_fmt', fmt)
            setattr(self, '_fmt', fmt)
        server_params = {
            "username": config.JENKINS_USER,
            "password": config.JENKINS_PASSWORD,
            "timeout": 10,
        }
        if url:
            self.url = url
            _url = url.strip("/")
            parsed = parse("{server}/job/{job_name}/{build_number}", _url)

            if parsed:
                self.number = int(parsed['build_number'])
                self.server = jenkins.Jenkins(parsed['server'], **server_params)
                self.name = parsed['job_name']
            else:
                parsed = parse("{server}/job/{job_name}", _url)
                self.server = jenkins.Jenkins(parsed['server'], **server_params)
                self.name = parsed['job_name']
                info = self.server.get_job_info(parsed['job_name'])
                if info.get(last_build_link):
                    self.number = int(info[last_build_link]['number'])
                else:
                    self.number = ""
                self.url = f"{_url}/{self.number}"
        else:
            self.name = job_name

            if isinstance(server, str):
                server = jenkins.Jenkins(server, **server_params)
            self.server = server

            if build_number is None:
                self.number = self.server.get_job_info(job_name)[
                    last_build_link]['number']
            else:
                self.number = int(build_number)

            self.url = f"{self.server.server}/job/{self.name}/{self.number}"
            if not http_adapter:
                http_adapter = HTTPAdapter(max_retries=retry)
            self.server._session.mount("http://", http_adapter)
            self.server._session.mount("https://", http_adapter)

    @classmethod
    def fmt(cls):
        # cls._fmt = fmt
        return cls._fmt

    def __repr__(self):
        # print("DEBUG: started __repr__")
        return f"{self.name}#{self.number}"

    def __format__(self, format_spec=None):
        # print("DEBUG: started __format__")
        format_spec = Build.fmt()
        if not format_spec:
            return str(self)
        return format_spec.format(**self.__dict__,
                                  status=self.status,
                                  duration=self.duration,
                                  start_time=self.start_time,
                                  display_name=self.display_name,
                                  param=self.param,
                                  parent=self.parent,
                                  triggered_by=self.triggered_by
                                  )

    @property
    def param(self):
        if not self.is_exist():
            return dict()
        return Params(**self.get_build_parameters())

    @functools.lru_cache
    def get_build_parameters(self) -> dict:
        build_info = self.server.get_build_info(self.name, self.number)
        parameters = jmespath.search("actions[*].parameters", build_info)
        if not parameters:
            return dict()
        d = {param['name']: param.get('value')
             for param in parameters[0]
             if param.get("name")}
        return d

    @property
    def _crumb(self):
        if not self.__crumb:
            self.server.get_nodes()
            self.__crumb = self.server.crumb.get("crumb")
        return self.__crumb


    @property
    def parent(self):
        if self._parent: return self._parent
        if not self.number: return None

        found = jmespath.search(
            "actions[*].causes[?contains(_class,'BuildUpstreamCause')]",
            self.get_build_info())[0]
        if not found:
            found = jmespath.search(
                "actions[*].causes[?contains(_class,"
                "'hudson.model.Cause$UpstreamCause')]",
                self.get_build_info())[0]
        # print(found)
        if not found:
            # print(f"Returned parent=None for {self}")
            return None
        if len(found) >= 2:
            print(f"{self.url} Oops! Found two causes!! {found=}")
        parent_job = Build(job_name=found[0]["upstreamProject"],
                           build_number=found[0]["upstreamBuild"],
                           server=self.server
                           )
        self._parent = parent_job
        return parent_job

    @property
    def children(self) -> list:
        if self._children: return self._children
        try:
            logs = self.server.get_build_console_output(self.name, self.number)
        except jenkins.JenkinsException as e:
            print(f"{e}")
            return []
        result = list()
        for line in logs.split('\n'):
            if not "Starting building:" in line: continue
            for entry in line.split("Starting"):
                parsed = parse("{}building: {name} #{number}", entry)
                if parsed is None: continue
                result.append(Build(job_name=parsed['name'],
                                    build_number=parsed['number'],
                                    server=self.server))
        self._children = result
        return result

    @property
    def heirs(self):
        if self._heirs: return self._heirs
        self._heirs = children(self)
        return self._heirs

    def get_child_jobs(self, name_pattern):
        return [ch
                for ch in self.heirs
                if name_pattern in ch.name]

    @functools.lru_cache(maxsize=10)
    def get_build_info(self):
        LOG.debug("Started get_build_info for " + str(self))
        return self.server.get_build_info(self.name, self.number)

    def build(self):
        raise NotImplemented
        return self.server.build_job(self.name, token="")

    def is_in_queue(self):
        try:
            queue = self.server.get_queue_info()
        except jenkins.NotFoundException as e:
            return False
        return self.name in [j["task"]["name"] for j in queue]

    def is_exist(self):
        if not self.number:
            return False
        try:
            self.server.get_build_info(self.name, self.number)
        except jenkins.JenkinsException:
            return False
        except BaseException:
            return False

        return True

    @property
    def status(self):
        if not self.is_exist():
            return "NOT_EXIST"
        if self.get_build_info().get('building'):
            return "BUILDING"
        return self.get_build_info().get('result')

    @property
    def display_name(self):
        return self.get_build_info().get('displayName')

    @display_name.setter
    def display_name(self, text):
        """
        Requires JENKINS_USER and JENKINS_PASSWORD
        """
        if not os.environ.get("JENKINS_USER") or not os.environ.get("JENKINS_PASSWORD"):
            raise RuntimeError("JENKINS_USER and JENKINS_PASSWORD not set")
        data = {
            "json": {
                "Jenkins-Crumb": self._crumb,
                "displayName": f"#{self.number} {text}",
                }
            }
        r = self.server.jenkins_request(
            requests.Request(
                'POST',
                url=f"{self.url}/configSubmit",
                data=urllib.parse.urlencode(data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Jenkins-Crumb": self._crumb}
                )
            )
        print(f"Updating displayName to {data['json']['displayName']} "
              f"completed with code {r.status_code}")

    @property
    def description(self) -> str:
        return self.get_build_info()["description"] or ""

    @description.setter
    def description(self, text):
        """
        Requires JENKINS_USER and JENKINS_PASSWORD
        """
        if not os.environ.get("JENKINS_USER") or not os.environ.get("JENKINS_PASSWORD"):
            raise RuntimeError("JENKINS_USER and JENKINS_PASSWORD not set")
        data = {
                "description": f"{text}",
                "Submit": ""
            }
        r = self.server.jenkins_request(
            requests.Request(
                'POST',
                url=f"{self.url}/submitDescription",
                data=urllib.parse.urlencode(data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Jenkins-Crumb": self._crumb}
                )
            )
        print(f"Updating description to {data['description']} "
              f"completed with code {r.status_code}")

    @property
    def triggered_by(self):
        if not self.number: return "Not built yet"

        found = jmespath.search(
            "actions[*].causes[?contains(_class,'hudson.model.Cause$UserIdCause')]",
            self.get_build_info())[0]
        if found:
            return found[0]["userId"]

        found = jmespath.search("actions[*].causes[?contains(_class,'hudson.triggers.TimerTrigger$TimerTriggerCause')]",
            self.get_build_info())[0]

        if found:
            return "timer"
        return

    @property
    def start_time(self) -> datetime.datetime:
        _timestamp = self.get_build_info().get('timestamp')
        if not _timestamp:
            return None
        # Divided by 1000 because Jenkins has timestamp in microseconds but
        # datetime lib receives in milliseconds
        return datetime.datetime.fromtimestamp(_timestamp / 1000)


    @property
    def duration(self):
        delta = datetime.timedelta(
            seconds=self.get_build_info().get('duration', 0) // 1000)
        return delta

    # def _get_stages(self):
    #     raise NotImplementedError
    #     # TODO: complete this
    #     resp = requests.Request(method='GET', url=self.url + "/wfapi/describe")
    #     return resp.json().get('stages')

    # def rebuild(self, params: dict = None):
    #     raise NotImplementedError
    #     # TODO: complete this
    #     if not params:
    #         return
    #     for param, value in params:
    #         pass

    def get_logs(self, read_from_end=False):
        logs = self.server.get_build_console_output(self.name, self.number)
        direction_read = slice(None, None, -1) \
            if read_from_end \
            else slice(None, None, 1)
        for line in logs.split("\n")[direction_read]:
            yield line

    def has_log_line(self, text):
        for line in self.get_logs():
            if text in line:
                LOG.debug(f"found text {text} in line {line}")
                return True
        return False

    def get_artifacts(self, filename_pattern=""):
        """

        """
        location_of_downloaded = list()
        for artifact in self.get_build_info()["artifacts"]:
            if not filename_pattern in artifact.get("displayPath"):
                continue
            url = f"{self.url}/artifact/{artifact['relativePath']}"
            file_location = f"/tmp/{artifact['fileName']}"
            self.download_file(url, file_location)
            location_of_downloaded.append(file_location)
            print(f"Saved to {file_location}")

        return location_of_downloaded

    @staticmethod
    def download_file(url, filename):
        response = requests.get(
            url,
            auth=(config.JENKINS_USER, config.JENKINS_PASSWORD),
            stream=True)
        with open(filename, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024):
                file.write(chunk)
        print(f"Saved to {filename}")
        return filename

    def get_link_from_description(self, pattern=""):
        links = re.findall(r"http[s?]\://[a-z0-9\:\.\/\-\?\&_]+",
                          self.description)
        return list(filter(lambda link: pattern in link, links))

    def update_build_config(self, display_name):
        self.server.submit_build(self.name, self.number,
                                 {
                                     "display_name": display_name
                                 })


def diff_job_params(urls, diff_only=False, to_html=False, fmt=None):
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is not installed. Reinstall with "
                          "'pip install jenkins-jinny[full]' command")
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)

    builds = [Build(url, fmt=fmt) for url in urls]
    data = dict()

    params = [build.get_build_parameters() for build in builds]
    all_keys = sorted(
        set(sum(
            [list(build_params.keys()) for build_params in params], []
        )))

    for build_params in params:
        for key in all_keys:
            data[key] = data.get(key, [])
            data[key].append(build_params.get(key, "n/d"))

    # print(data)
    headers = [f"{build}" for build in builds]
    print(headers)
    table = pd.DataFrame.from_dict(data, columns=headers, orient='index',
                                   dtype=str)
    if diff_only:
        # A lot of pandas magic to find diff in table
        dd = table.ne(table[headers[0]], axis='index')
        da = dd[dd == True]
        da = da.any(axis='columns')
        row_to_drop = da[da == False]

        table = table.drop(row_to_drop.index)

    if to_html:
        file_path = pathlib.Path.cwd() / "diff.html"
        with open(file_path, 'w') as f:
            f.write(table.to_html())
            print(f"Saved to file://{file_path.as_posix()}")
        table.to_html()
    else:
        print(table)


def parents(build):
    _p = build.parent
    if _p is None: pass
    yield _p
    yield from parents(_p)


def children(build):
    """
        Returns all children (with grandchildren)
    """
    _children = build.children
    if _children.__len__() == 0: pass
    for child in _children:
        yield child
        yield from children(child)


def find_root(build: Build):
    for node in parents(build):
        if node is None: return build
        # print(f"{node=} in parents of {build=}")
        if node.parent is None:
            print(f"Found root {node=}")
            return node


def build_flow(url, fmt):
    if fmt:
        globals()['fmt'] = fmt
    build = Build(url=url, fmt=fmt)
    _jenkins = build.server
    G = nx.DiGraph()
    root_node = find_root(build)
    G.add_node(str(root_node), label="root")
    for child in children(root_node):
        G.add_node(str(child))
        G.add_edge(str(child.parent), str(child))
        # print(f"{child}= from {child.parent=}")
    T = nx.dfs_tree(G, str(root_node))
    for node in T:
        depth = nx.shortest_path_length(G, source=str(root_node), target=node)
        job_name, build_number = parse("{}#{}", node)
        build = Build(job_name=job_name,
                      build_number=build_number,
                      server=_jenkins)
        print(f"{'  ' * depth} {build}")

    # ipdb.set_trace()
    # nx.write_latex(G, "just_my_figure.tex")

    # nx.draw(G, with_labels=True, font_weight='bold')
    # print("Opened new window with graph.
    # Close it before proceeding further...")
    # plt.show()


def show_possible_upstreams(url, fmt, limit=10):
    build = Build(url=url, fmt=fmt)
    for i in range(limit):
        print(f"{build} was triggered by {build.parent}")
        previous = jmespath.search("previousBuild.url", build.get_build_info())
        build = Build(url=previous)
    return


def debug_build(build, fmt):
    b = Build(build, fmt=fmt)
    print(f"{b}")
    ipdb.set_trace()


def search_build(url, condition, limit, fmt):
    build = Build(url=url, fmt=fmt)
    list_of_conditions = condition.split(",")

    def _operator(action):
        _op = "contain"
        match action:
            case '=':
                _op = "eq"
            case '>':
                _op = "contains"
        return _op

    for i in range(limit):
        found = True
        for cond in list_of_conditions:
            parsed = parse("{param} {action} {value}", cond)
            # print(f"{parsed=}")
            param = parsed['param'].strip()
            action = parsed['action'].strip()
            value = parsed['value'].strip()
            # print(f"actual = {build.get_build_parameters().get(param)}")
            if not getattr(operator, _operator(action))(
                    str(build.get_build_parameters().get(param)),
                    str(value)):
                found = False

        if found:
            # print(
            #     f"{build.__repr__():40} {build.duration} {build.status:12} {build.url}")
            yield build

        previous = jmespath.search("previousBuild.url", build.get_build_info())
        if previous is None:
            print(f"Can't get previous build")
            break
        build = Build(url=previous)


def show_param(url, params, limit, fmt):
    build = Build(url=url, fmt=fmt)
    list_of_params = params.split(",")

    for i in range(limit):
        param_values = []
        for p in list_of_params:
            param_values.append(str(build.get_build_parameters().get(p)))
        formatted_params = "\t".join(param_values)
        print(
            f"{build}\t"
            f"{formatted_params}")

        previous = jmespath.search("previousBuild.url", build.get_build_info())
        if previous is None:
            print(f"Can't get previous build")
            break
        build = Build(url=previous)

def search_log(url, pattern, limit, fmt):
    build = Build(url=url, fmt=fmt)
    for i in range(limit):
        if build.has_log_line(pattern):
            print(f"{build}")

        previous = jmespath.search("previousBuild.url", build.get_build_info())
        if previous is None:
            print(f"Can't get previous build")
            break
        build = Build(url=previous)



def jobs_in_view(view_url: str, fmt: str) -> List[Build]:
    """
    Returns list of job (in Build type)
    """
    view_url = view_url.strip("/")
    parsed_view_url = parse("{server}/view/{name}", view_url)
    server_url = parsed_view_url["server"]
    view_name = parsed_view_url["name"]
    _server = jenkins.Jenkins(server_url)

    jobs = _server.get_jobs(view_name=view_name)
    for job in jobs:
        try:
            # print(job['url'])
            # print(f"{Build(url=job['url'])}")
            yield Build(url=job['url'], fmt=fmt)
        except TypeError as e:
            print(f"Occurred error {e}")
            # raise f"Occurred error {e}"
