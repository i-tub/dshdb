HIST_DIR?=~/.hist

help:
	@echo "Available targets:"
	@echo "- install: install to \$$HIST_DIR (default: $(HIST_DIR))"
	@echo "- test: run unit tests"
	@echo "- shell: enter a bash subshell using the CWD as \$$HIST_DIR,"
	@echo "  with a copy of the hist.db for testing"

test:
	python2 test.py
	python3 test.py

install:
	@echo Copying files to $(HIST_DIR)...
	@mkdir -p $(HIST_DIR)
	@cp hist.py $(HIST_DIR)
	@cp hist.sh $(HIST_DIR)
	@echo "To activate, make sure your .bashrc has"
	@echo "   . $(HIST_DIR)/hist.sh"

shell:
	@echo Entering shell with \$$HIST_DIR=$(PWD)
	@cp $(HIST_DIR)/hist.db .
	@HIST_DIR=${PWD} HIST_DEBUG=1 bash
