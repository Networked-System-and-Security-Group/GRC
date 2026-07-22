echo -n "$(date)Running small flow incast test with different configurations, [$(cat ./mix/index.txt), " >> ./mix/history.txt
./waf
for i in 25 30 35 40 45; do
    python3 run.py --my_flow simple_flow2-$i --topo wan_simple_topo --wan_cc_mode 0
    sleep 3
    python3 run.py --my_flow simple_flow2-$i --topo wan_simple_topo --wan_cc_mode 2
    sleep 3
    python3 run.py --my_flow simple_flow2-$i --topo wan_simple_topo --wan_cc_mode 1
    sleep 3
done
echo "$(cat ./mix/index.txt)]" >> ./mix/history.txt