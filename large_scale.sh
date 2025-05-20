echo -n "$(date)Running large scale test with different configurations, [$(cat ./mix/index.txt), " >> ./mix/history.txt
./waf
sleep 3
time=0.1
for i in 140 160; do
    python3 run.py --inter_load_all $i --wan_cc_mode 0 --simul_time $time
    sleep 3
    python3 run.py --inter_load_all $i --wan_cc_mode 2 --simul_time $time
    sleep 3
    python3 run.py --inter_load_all $i --wan_cc_mode 1 --simul_time $time
    sleep 3
done
echo "$(cat ./mix/index.txt)]" >> ./mix/history.txt