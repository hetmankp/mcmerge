all: dist/merge.zip

FORCE:

dist/merge.exe: FORCE
	python setup.py py2exe

dist/merge.zip: dist/merge.exe
	(cd dist; zip -m merge.zip merge.exe merge.lib)
