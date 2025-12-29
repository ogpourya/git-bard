from setuptools import setup

setup(
    name="git-bard",
    version="1.0.0",
    py_modules=["git_bard"],
    install_requires=[
        "google-genai",
    ],
    entry_points={
        "console_scripts": [
            "git-bard=git_bard:main",
        ],
    },
    python_requires=">=3.9",
)
