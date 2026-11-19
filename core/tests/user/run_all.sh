#!/usr/bin/env bash
# Owner user tests. Claude-only runs in parallel (Max, no GPU); local + both-model tests one at a time (Ollama).
cd /home/naitikg/code/quintacle/core
OUT=${1:-/tmp/claude-1000/-home-naitikg-code-quintacle/7c63c129-cb92-43b2-821d-b26647998c45/scratchpad/user-run}
mkdir -p $OUT
run() { name=$1; prov=$2; f=$3
  QUINTACLE_USER_PROVIDER=$prov .venv/bin/python -m pytest $f -q -s -rfE -p no:cacheprovider > $OUT/$name.log 2>&1
  echo "$name: $(tail -1 $OUT/$name.log)"; }
for t in travel/test_t01_austria_drop travel/test_t03_europe_2027_flight food/test_t05_lamb_label_ingredient food/test_t06_greek_yogurt_label food/test_t09_yogurt_already_saved; do
  ( run "$(basename $t)-claude" cloud tests/user/$t.py ) &
done
for t in travel/test_t01_austria_drop travel/test_t03_europe_2027_flight food/test_t05_lamb_label_ingredient food/test_t06_greek_yogurt_label food/test_t09_yogurt_already_saved; do
  run "$(basename $t)-local" local tests/user/$t.py
done
for t in food/test_t07_breakfast_chat food/test_t08_usual_breakfast food/test_t10_lamb_burger_recipe workout/test_t11_pull_day_chat travel/test_t02_nyc_2028_chat food/test_t04_full_day_meal_plan_chat; do
  run "$(basename $t)-both" local tests/user/$t.py
done
wait
echo ALL DONE
