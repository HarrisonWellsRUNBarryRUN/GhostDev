#!/usr/bin/env bash
# ==============================================================================
# GhostDev: Autonomous Terminal Session Player / asciinema recorder
# Usage:
#   ./render_demo.sh
#   asciinema rec ghostdev_demo.cast -c ./render_demo.sh
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

type_cmd() {
    local text="$1"
    local delay=0.03
    echo -ne "${BOLD}${PURPLE}ghostdev${NC}:${BOLD}${BLUE}~/repo${NC}$ "
    sleep 0.4
    for (( i=0; i<${#text}; i++ )); do
        echo -n "${text:$i:1}"
        sleep $delay
    done
    echo ""
    sleep 0.3
}

clear
echo -e "${BOLD}${PURPLE}👻 GhostDev Automation Engine Initialized...${NC}\n"
sleep 0.8

# ------------------------------------------------------------------------------
# ACT 1: THE BROKEN BASELINE
# ------------------------------------------------------------------------------
type_cmd "pytest test_sample_app.py"
echo -e "${BOLD}============================= test session starts =============================${NC}"
echo -e "collected 4 items\n"
echo -e "test_sample_app.py ..${RED}F${NC}.                                                  [100%]\n"
echo -e "${RED}=================================== FAILURES ===================================${NC}"
echo -e "${RED}___________________________ test_divide_numbers_zero ___________________________${NC}"
echo -e "    def test_divide_numbers_zero():"
echo -e ">       assert divide_numbers(10, 0) is None"
echo -e "${BOLD}sample_app.py:11: ZeroDivisionError: division by zero${NC}"
echo -e "${RED}=========================== 1 failed, 3 passed in 0.16s =========================${NC}\n"
sleep 2.5

# ------------------------------------------------------------------------------
# ACT 2: SURGICAL INTERVENTION
# ------------------------------------------------------------------------------
type_cmd "git diff 4b24533 sample_app.py"
echo -e "${BOLD}diff --git a/sample_app.py b/sample_app.py${NC}"
echo -e "--- a/sample_app.py"
echo -e "+++ b/sample_app.py"
echo -e "@@ -7,5 +7,10 @@ def divide_numbers(a: float, b: float):"
echo -e "${RED}-    # Intentional Bug: Throws ZeroDivisionError when b == 0${NC}"
echo -e "${RED}-    return a / b${NC}"
echo -e "${GREEN}+    try:${NC}"
echo -e "${GREEN}+        val_a = float(a)${NC}"
echo -e "${GREEN}+        val_b = float(b)${NC}"
echo -e "${GREEN}+        if val_b == 0.0:${NC}"
echo -e "${GREEN}+            return None${NC}"
echo -e "${GREEN}+        return val_a / val_b${NC}"
echo -e "${GREEN}+    except (ZeroDivisionError, OverflowError, TypeError, ValueError):${NC}"
echo -e "${GREEN}+        return None${NC}\n"
sleep 2.5

# ------------------------------------------------------------------------------
# ACT 3: PERMANENT REGRESSION SYNTHESIS
# ------------------------------------------------------------------------------
type_cmd "pytest -v tests/generated_regressions/test_regression_divide_by_zero.py"
echo -e "${BOLD}============================= test session starts =============================${NC}"
echo -e "collected 27 items\n"
echo -e "tests/.../test_regression_divide_by_zero.py::valid_int_division ${GREEN}PASSED${NC}         [  3%]"
echo -e "tests/.../test_regression_divide_by_zero.py::zero_denominator_int ${GREEN}PASSED${NC}      [ 25%]"
echo -e "tests/.../test_regression_divide_by_zero.py::stringified_zero_denom ${GREEN}PASSED${NC}    [ 48%]"
echo -e "tests/.../test_regression_divide_by_zero.py::none_denominator ${GREEN}PASSED${NC}          [ 66%]"
echo -e "tests/.../test_regression_divide_by_zero.py::large_int_overflow_309 ${GREEN}PASSED${NC}    [ 92%]"
echo -e "tests/.../test_regression_divide_by_zero.py::never_raises_unhandled ${GREEN}PASSED${NC}     [100%]"
echo -e "${GREEN}============================== 27 passed in 0.10s ==============================${NC}\n"
sleep 2.5

# ------------------------------------------------------------------------------
# ACT 4: TELEMETRY BANNER
# ------------------------------------------------------------------------------
echo -e "${CYAN}===================================================================================${NC}"
echo -e "${BOLD}${PURPLE}   👻 GHOSTDEV: AUTONOMOUS MULTI-AGENT HEALING & AUDIT VERIFIED ${NC}"
echo -e "${GREEN}   ✔ Model Routing Stack  : Claude 3.5 Sonnet (Coder) + GPT-4o-mini (Tester)${NC}"
echo -e "${GREEN}   ✔ Token Efficiency     : 12,480 tokens (Prompt: 9.1k, Comp: 3.3k) • Cost: $0.038${NC}"
echo -e "${YELLOW}   ✔ Adversarial Guard    : 100% Pass Rate (27/27 Regressions + Boundary Traps)${NC}"
echo -e "${BLUE}   ✔ Release Provenance   : Branch: fix/divide-zero [Commit: 969ca42] in 0.18s${NC}"
echo -e "${CYAN}===================================================================================${NC}\n"
sleep 3.0
