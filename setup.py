import os, glob
from distutils.core import setup
import py2exe

def find_data_files(source,target,patterns):
    """Locates the specified data-files and returns the matches
    in a data_files compatible format.

    source is the root of the source data tree.
        Use '' or '.' for current directory.
    target is the root of the target data tree.
        Use '' or '.' for the distribution directory.
    patterns is a sequence of glob-patterns for the
        files you want to copy.
    """
    if glob.has_magic(source) or glob.has_magic(target):
        raise ValueError("Magic not allowed in src, target")
    ret = {}
    for pattern in patterns:
        pattern = os.path.join(source,pattern)
        for filename in glob.glob(pattern):
            if os.path.isfile(filename):
                targetpath = os.path.join(target,os.path.relpath(filename,source))
                path = os.path.dirname(targetpath)
                ret.setdefault(path,[]).append(filename)
    return sorted(ret.items())

setup(
    console=['mcmerge.py'],
    zipfile='mcmerge.lib',
    options={'py2exe': dict(
        dist_dir = 'build/winexe',
        bundle_files = 1,
        compressed = True,
        unbuffered = True,
        includes = ['pkg_resources'],
        excludes = ['Tkconstants', 'Tkinter', 'tcl'],
        dll_excludes = ['w9xpopen.exe', 'mswsock.dll', 'powrprof.dll'],
    )},
    data_files=find_data_files('pymclevel', 'pymclevel', ['*.yaml', 'schematics/*', 'schematics/**/*']),
    author='Przemyslaw Wrzos',
    license='MIT License',
)
