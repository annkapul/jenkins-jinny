import os
from setuptools import setup, find_packages


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


def get_requirements_list(requirements):
    all_requirements = read(requirements)
    return all_requirements


setup(
    name='jenkins-jinny',
    version='1.0.0',
    packages=find_packages(include=['jenkins_jinny']),
    url='',
    license='',
    author='harhipova',
    author_email='',
    description='',
    python_requires='>=3.10',
    entry_points={
        'console_scripts': [
            'jenkins-jinny = jenkins_jinny.cli:start',
        ]
    },
    install_requires=get_requirements_list('./requirements.txt'),
)
