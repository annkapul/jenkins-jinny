import click
from . import main
import contextlib
import ipdb

PDB_HELP = "Flag to start Pdb immediately after causing an exception"
FORMAT_HELP = """Format build info "{url} {status} {param.OPTIONS}" 
Syntax is similar to python f-strings 
\n\b
Available variables:
- duration
- display_name
- url
- name
- number
- status 
- start_time
- param.NAME_OF_PARAMETER where NAME_OF_PARAMETER is parameter from job

"""

def pdb_context(enable_pdb):
    if enable_pdb:
        return ipdb.launch_ipdb_on_exception()
    return contextlib.nullcontext()


@click.group()
def cli():
    pass


@cli.command()
@click.argument('urls', nargs=-1)
@click.option('-f', 'fmt', default="", help=FORMAT_HELP)
@click.option('--diff', 'diff_only', is_flag=True, default=False)
@click.option('--to-html', 'to_html', is_flag=True, default=False)
@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def diff_job_params(urls, to_html, diff_only, with_pdb, fmt):
    with pdb_context(with_pdb):
        main.diff_job_params(urls=urls,
                             diff_only=diff_only,
                             to_html=to_html, fmt=fmt)


@cli.command()
@click.argument('url', nargs=1)
@click.option('-f', 'fmt', default="", help=FORMAT_HELP)
@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def build_flow(url, fmt, with_pdb):
    with pdb_context(with_pdb):
        main.build_flow(url, fmt)


@cli.command()
@click.argument('url', nargs=1)
@click.option('--limit', 'limit', default=10)
@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def show_possible_upstreams(url, limit, with_pdb):
    """
    Shows a parent job for first 10 jobs starting from defined job

    LIMIT can be changed by --limit option

    """
    with pdb_context(with_pdb):
        main.show_possible_upstreams(url, limit=limit)


@cli.command()
@click.argument('build')
def debug_build(build):
    main.debug_build(build)


@cli.command()
@click.argument('url')
@click.argument('condition')
@click.option('-f', 'fmt', default="", help=FORMAT_HELP)
@click.option('--limit', 'limit', default=50)
@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def search_build(url, condition, fmt, limit, with_pdb):
    """
    Search build with defined parameter in job history

    \b
    CONDITION can look like:
    START_TESTS=true,JENKINS_AGENT>python
    Use = for exact equality
        > for checking that parameter has that substring
        , to separate several conditions
    """
    with pdb_context(with_pdb):
        main.search_build(url, condition,
                                 limit=limit, fmt=fmt)


@cli.command()
@click.argument('url')
@click.argument('params')
@click.option('--limit', 'limit', default=50, help="Limit of jobs to search "
                                                   "in history")
@click.option('-f', 'fmt', default="", help=FORMAT_HELP)

@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def show_param(url, params, limit, with_pdb, fmt):
    """
    Shows parameter value for first 50 jobs

    """
    with pdb_context(with_pdb):
        main.show_param(url, params,
                        limit=limit,
                        fmt=fmt)


@cli.command()
@click.argument('view_url')
@click.option('-f', 'fmt', default="", help=FORMAT_HELP)
@click.option("--pdb", "with_pdb", is_flag=True, default=False, help=PDB_HELP)
def jobs_in_view(view_url, fmt, with_pdb):
    with pdb_context(with_pdb):
        for j in main.jobs_in_view(view_url, fmt):
            print(j)



def start():
    cli()