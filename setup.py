"""
Fallback setup.py for older pip / setuptools that don't read pyproject.toml.
All canonical config lives in pyproject.toml.
"""
from setuptools import setup, find_packages

setup(
    name="sysdock",
    version="1.2.1",
    description="SysDock — Linux / EC2 monitoring agent with live terminal dashboard and Docker metrics",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    python_requires=">=3.6",
    packages=find_packages(include=["infravision_agent", "infravision_agent.*"]),
    install_requires=[
        "psutil>=5.8.0",
        "rich>=12.0.0",
        "click>=7.0",
    ],
    extras_require={
        "docker": ["docker>=5.0.0"],
        "server": ["flask>=2.0"],
        "all":    ["docker>=5.0.0", "flask>=2.0"],
    },
    entry_points={
        "console_scripts": [
            "sysdock=infravision_agent.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Monitoring",
    ],
)
