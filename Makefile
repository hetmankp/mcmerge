TAG ?= $(shell date '+%Y%m%d_%H%M')
WIN32_PKG = mcmerge-win32-$(TAG).zip
SCRPT_PKG = mcmerge-script-$(TAG).zip
BUILD_DIR = build
DIST_DIR = dist
SCRPT_BUILD = $(BUILD_DIR)/assemble

all: $(DIST_DIR)/$(SCRPT_PKG) $(DIST_DIR)/$(WIN32_PKG)

clean:
	-rm -r $(BUILD_DIR)
	-rm -r $(DIST_DIR)

FORCE:

$(DIST_DIR)/mcmerge.exe: FORCE
	python setup.py py2exe

$(DIST_DIR)/$(WIN32_PKG): $(DIST_DIR)/mcmerge.exe
	mkdir -p $(DIST_DIR)
	cp README.txt $(DIST_DIR)
	(cd $(DIST_DIR); zip -m $(WIN32_PKG) mcmerge.exe mcmerge.lib README.txt)

$(DIST_DIR)/$(SCRPT_PKG): FORCE
	mkdir -p $(DIST_DIR)
	-rm -r $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)/pymclevel
	cp LICENCE.txt README.txt *.py $(SCRPT_BUILD)
	cp $(addprefix pymclevel/,LICENSE.txt README.txt items.txt *.py) $(SCRPT_BUILD)/pymclevel
	(cd $(SCRPT_BUILD); zip -r $(SCRPT_PKG) *)
	mv $(SCRPT_BUILD)/$(SCRPT_PKG) $(DIST_DIR)/$(SCRPT_PKG)
