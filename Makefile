TAG ?= $(shell date '+%Y%m%d_%H%M')
WIN32_PKG = merge-win32-$(TAG).zip
SCRPT_PKG = merge-script-$(TAG).zip
BUILD_DIR = build
DIST_DIR = dist
SCRPT_BUILD = $(BUILD_DIR)/assemble

all: $(DIST_DIR)/$(SCRPT_PKG) $(DIST_DIR)/$(WIN32_PKG)

clean:
	-rm -r $(BUILD_DIR)
	-rm -r $(DIST_DIR)

FORCE:

$(DIST_DIR)/merge.exe: FORCE
	python setup.py py2exe

$(DIST_DIR)/$(WIN32_PKG): $(DIST_DIR)/merge.exe
	(cd $(DIST_DIR); zip -m $(WIN32_PKG) merge.exe merge.lib)

$(DIST_DIR)/$(SCRPT_PKG): FORCE
	mkdir -p $(DIST_DIR)
	-rm -r $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)/pymclevel
	cp LICENCE.txt README.txt *.py $(SCRPT_BUILD)
	cp $(addprefix pymclevel/,LICENSE.txt README.txt items.txt *.py) $(SCRPT_BUILD)/pymclevel
	(cd $(SCRPT_BUILD); zip -r $(SCRPT_PKG) *)
	mv $(SCRPT_BUILD)/$(SCRPT_PKG) $(DIST_DIR)/$(SCRPT_PKG)
