from distutils.core import setup
import py2exe

setup(
    console=['mcmerge.py'],
    zipfile='mcmerge.lib',
    options={'py2exe': dict(
        dist_dir = 'dist',
        bundle_files = 1,
        compressed = True,
        unbuffered = True,
        excludes = ['Tkconstants', 'Tkinter', 'tcl', 'scipy'],
        dll_excludes = ['w9xpopen.exe', 'mswsock.dll', 'powrprof.dll'],
    )}
)
