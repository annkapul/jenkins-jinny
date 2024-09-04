import enum

import numpy as np

import jenkins
import jmespath
import pandas as pd
import requests
from parse import parse
import networkx as nx
import ipdb
import pathlib
import datetime
import operator
from typing import List
from .exceptions import BuildNotFoundException

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)


class Params:
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def __getattr__(self, name):
        # Do not throw Attribute error if object doesn't have an attribute
        # with 'name'
        return "noitem"

    def __repr__(self):
        return " ".join(f"{k}={v}" for k, v in self.__dict__.items())

class LastBuildLinks(str, enum.Enum):
    LAST_BUILD = 'lastBuild'
    LAST_COMPLETED = "lastCompletedBuild"
    LAST_FAILED = "lastFailedBuild"
    LAST_SUCCESSFUL = "lastSuccessfulBuild"
    LAST_UNSUCCESSFUL = "lastUnsuccessfulBuild"




class Build:
    def __init__(self,
                 url=None,
                 job_name=None,
                 build_number=None,
                 server=None,
                 last_build_link=LastBuildLinks.LAST_BUILD):
        """
        :param url: full url address of job. It will be parsed into server,
        job_name, build_number

        :param job_name: name of job (without jenkins url anf view's name)

        :param build_number: int , number of the build. Returns latest build
        if not defined

        :param server: str with url of Jenkins server or jenkins.Jenkins object
        """
        self._parent = None
        self._heirs = None
        self._children = list()
        server_params = {}
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

    def __repr__(self):
        return f"{self.name}#{self.number}"

    def __format__(self, format_spec=None):
        format_spec = globals().get("fmt", None)
        if not format_spec:
            return str(self)
        return format_spec.format(**self.__dict__,
                                  status=self.status,
                                  duration=self.duration,
                                  start_time=self.start_time,
                                  display_name=self.display_name,
                                  param=self.param
                                  )

    @property
    def param(self):
        return Params(**self.get_build_parameters())

    def get_build_parameters(self):
        build_info = self.server.get_build_info(self.name, self.number)
        parameters = jmespath.search("actions[*].parameters", build_info)[0]
        d = {param['name']: param['value'] for param in parameters}
        return d

    @property
    def parent(self):
        if self._parent: return self._parent
        try:
            build_info = self.server.get_build_info(self.name, self.number)
        except jenkins.JenkinsException as e:
            print(f"{e}")
            return None

        found = jmespath.search(
            "actions[*].causes[?contains(_class,'BuildUpstreamCause')]",
            build_info)[0]
        if not found:
            found = jmespath.search(
                "actions[*].causes[?contains(_class,"
                "'hudson.model.Cause$UpstreamCause')]",
                build_info)[0]
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

    def get_child_job(self, name_pattern):
        return [ch
                for ch in self.heirs
                if name_pattern in ch.name]

    def get_build_info(self):
        return self.server.get_build_info(self.name, self.number)

    def build(self):
        raise NotImplemented
        return self.server.build_job(self.name, token="")

    def is_in_queue(self):
        return self.name in [j["task"]["name"] for j in self.server.get_queue_info()]

    @property
    def status(self):
        if self.is_in_queue():
            return "IN_QUEUE"
        if self.get_build_info().get('building'):
            return "BUILDING"
        return self.get_build_info().get('result')

    @property
    def display_name(self):
        return self.get_build_info().get('displayName')

    @property
    def description(self):
        return self.get_build_info()["description"]

    @property
    def triggered_by(self):
        return

    @property
    def start_time(self):
        _timestamp = self.get_build_info().get('timestamp')
        if not _timestamp:
            return None
        # Divided by 1000 because Jenkins has timestamp in microseconds but
        # datetime lib receives in milliseconds
        return datetime.datetime.fromtimestamp(_timestamp / 1000)

    @property
    def duration(self):
        delta = datetime.timedelta(
            seconds=self.get_build_info().get('duration') // 1000)
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

    def get_artifacts_content(self, filename_pattern):
        return self.server.get_build_artifact_as_bytes(self.name, self.number, filename_pattern)

    def get_link_from_description(self):
        self.get_build_info()


def diff_job_params(urls, diff_only=False, to_html=False, fmt=None):
    if fmt:
        globals()['fmt'] = fmt
    builds = [Build(url) for url in urls]
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
    build = Build(url=url)
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


def show_possible_upstreams(url, limit=10):
    build = Build(url=url)
    for i in range(limit):
        print(f"{build} was triggered by {build.parent}")
        previous = jmespath.search("previousBuild.url", build.get_build_info())
        build = Build(url=previous)
    return


def debug_build(build):
    b = Build(build)
    ipdb.set_trace()


def search_build(url, condition, limit, fmt):
    if fmt:
        globals()['fmt'] = fmt
    build = Build(url=url)
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
            print(
                f"{build.__repr__():40} {build.duration} {build.status:12} {build.url}")

        previous = jmespath.search("previousBuild.url", build.get_build_info())
        if previous is None:
            print(f"Can't get previous build")
            break
        build = Build(url=previous)


def show_param(url, params, limit, fmt):
    if fmt:
        globals()['fmt'] = fmt
    build = Build(url=url)
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


def jobs_in_view(view_url: str, fmt: str) -> List[Build]:
    """
    Returns list of job (in Build type)
    """
    if fmt:
        globals()['fmt'] = fmt
    view_url = view_url.strip("/")
    parsed_view_url = parse("{server}/view/{name}", view_url)
    server_url = parsed_view_url["server"]
    view_name = parsed_view_url["name"]
    _server = jenkins.Jenkins(server_url)

    jobs = _server.get_jobs(view_name=view_name)
    for job in jobs:
        try:
            print(job['url'])
            print(Build(url=job['url']))
            yield Build(url=job['url'])
        except TypeError as e:
            print(f"Occurred error {e}")
            raise f"Occurred error {e}"
