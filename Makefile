TAG ?= $(shell date '+%Y%m%d_%H%M')
WIN32_PKG = mcmerge-win32-$(TAG).zip
SCRPT_PKG = mcmerge-script-$(TAG).zip
BUILD_DIR = build
DIST_DIR = dist
WINEXE_BUILD = $(BUILD_DIR)/winexe
SCRIPT_BUILD = $(BUILD_DIR)/script

all: $(DIST_DIR)/$(SCRPT_PKG) $(DIST_DIR)/$(WIN32_PKG)

clean:
	-rm -r $(BUILD_DIR)
	-rm -r $(DIST_DIR)

FORCE:

$(WINEXE_BUILD)/mcmerge.exe: FORCE
	python setup.py py2exe

$(WINEXE_BUILD)/LICENCE.txt: LICENCE.txt pymclevel/LICENSE.txt
	mkdir -p $(WINEXE_BUILD)
	echo "mcmerge licence" | unix2dos > $@
	echo "---------------" | unix2dos >> $@
	cat LICENCE.txt | unix2dos >> $@
	echo | unix2dos >> $@
	echo | unix2dos >> $@
	echo "pymclevel licence" | unix2dos >> $@
	echo "-----------------" | unix2dos >> $@
	cat pymclevel/LICENSE.txt | unix2dos >> $@

$(WINEXE_BUILD)/$(WIN32_PKG): $(WINEXE_BUILD)/mcmerge.exe $(WINEXE_BUILD)/LICENCE.txt
	mkdir -p $(WINEXE_BUILD)
	cat README.md | sed 's/\\\\/\\/g' > $(WINEXE_BUILD)/README.txt
	(cd $(WINEXE_BUILD); zip -r $(WIN32_PKG) *)

$(DIST_DIR)/$(WIN32_PKG): $(WINEXE_BUILD)/$(WIN32_PKG)
	mkdir -p $(DIST_DIR)
	mv $(WINEXE_BUILD)/$(WIN32_PKG) $(DIST_DIR)/$(WIN32_PKG)

$(SCRIPT_BUILD)/$(SCRPT_PKG): FORCE
	mkdir -p $(DIST_DIR)
	-rm -r $(SCRIPT_BUILD)
	mkdir -p $(SCRIPT_BUILD)
	cat README.md | sed 's/\\\\/\\/g' > $(SCRIPT_BUILD)/README.txt
	cp LICENCE.txt *.py $(SCRIPT_BUILD)
	find pymclevel -name '*.pyc' -o -name .gitignore \
	            -o \( -path */.git -o -path pymclevel/testfiles \
	            -o -path pymclevel/regression_test \) -prune -o -print \
	    | while read file; do if [ -d "$$file" ]; then mkdir -p "$(SCRIPT_BUILD)/$$file"; else cp "$$file" "$(SCRIPT_BUILD)/$$file"; fi; done
	cp $(addprefix pymclevel/,LICENSE.txt README.txt items.txt *.py *.yaml *.txt) $(SCRIPT_BUILD)/pymclevel
	(cd $(SCRIPT_BUILD); zip -r $(SCRPT_PKG) *)

$(DIST_DIR)/$(SCRPT_PKG): $(SCRIPT_BUILD)/$(SCRPT_PKG)
	mkdir -p $(DIST_DIR)
	mv $(SCRIPT_BUILD)/$(SCRPT_PKG) $(DIST_DIR)/$(SCRPT_PKG)
