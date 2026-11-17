#!/usr/bin/env bash
# I Lake 체크리스트 - K8s 노드에서 실행 (root)
#   sudo bash ilake-node-check.sh
#   출력 : "번호|값|판정"  판정 = OK(Y1 기준과 같음) / CHK(다름) / INFO(값만 기록) / NA(확인 불가)
#   번호 = sheet "I Lake 체크리스트" 번호. 이미 확인된 14 · 26 · 34 · 35 · 36 · 38 은 생략
#   control plane 노드에서 실행하면 Service · 풀 항목(28~33)까지 확인됨 (kubectl 필요)

OKS=(); CHKS=(); INFOS=(); NAS=()
out() {  # 번호 값 판정   (값 끝의 * = cilium-config 에 키 없음 → Cilium 기본값)
  printf "%s|%s|%s\n" "$1" "$2" "$3"
  case "$3" in OK) OKS+=("$1");; CHK) CHKS+=("$1=$2");; INFO) INFOS+=("$1=$2");; *) NAS+=("$1");; esac
}
eq()  { [ "${2%\*}" = "$3" ] && out "$1" "$2" OK || out "$1" "${2:--}" CHK; }   # 번호 값 기대값

# ---- Cilium agent 접근 (crictl 우선, 없으면 kubectl)
CID=$(crictl ps --name cilium-agent -q 2>/dev/null | head -1)
cx() { if [ -n "$CID" ]; then crictl exec "$CID" "$@" 2>/dev/null
       else kubectl -n kube-system exec ds/cilium -c cilium-agent -- "$@" 2>/dev/null; fi; }
cfg() { cx cat /tmp/cilium/config-map/$1 | tr -d '\n'; }
cfgd() { local v; v=$(cfg "$1"); [ -n "$v" ] && echo "$v" || echo "$2*"; }   # 키 없으면 기본값*

# ---- kubectl (control plane 노드면 admin.conf 사용)
K=0
if command -v kubectl >/dev/null; then
  kubectl get ns >/dev/null 2>&1 && K=1
  if [ $K = 0 ] && [ -r /etc/kubernetes/admin.conf ]; then export KUBECONFIG=/etc/kubernetes/admin.conf; kubectl get ns >/dev/null 2>&1 && K=1; fi
fi

echo "== I Lake check $(hostname -s) $(date +%m%d-%H%M) =="

# ===== Cilium (1~23)
CIL=0; [ -n "$(cfg routing-mode)" ] && CIL=1
if [ $CIL = 1 ]; then
eq 1  "$(cfg routing-mode)" native
eq 2  "$(cfgd kube-proxy-replacement false)" true
eq 3  "$(cfgd datapath-mode veth)" netkit
HR=$(cx cilium-dbg status --verbose | awk -F: '/Host Routing/{gsub(/ /,"",$2);print $2;exit}')
[ "$(cfg enable-host-legacy-routing)" != "true" ] && [ "$HR" = "BPF" ] && out 4 "BPF" OK || out 4 "${HR:-?}" CHK
KPR=$(cfgd kube-proxy-replacement false); eq 5  "$(cfgd bpf-lb-sock ${KPR%\*})" true
eq 6  "$(cfgd bpf-lb-algorithm random)" random
eq 7  "$(cfgd bpf-lb-algorithm-annotation false)" true
T=$(cfgd bpf-lb-maglev-table-size 16381); S=$( [ -n "$(cfg bpf-lb-maglev-hash-seed)" ] && echo set || echo def )
[ "${T%\*}" = "16381" ] && out 8 "$T,seed=$S" OK || out 8 "$T,seed=$S" CHK   # seed 기본값도 전 노드 동일
eq 9  "$(cfgd bpf-lb-mode snat)" dsr
D=$(cfgd bpf-lb-dsr-dispatch opt); TP=$(cfgd tunnel-protocol vxlan)
[ "${D%\*}" = "geneve" ] && out 10 "$D" OK || out 10 "$D,tp=$TP" CHK
eq 11 "$(cfgd bpf-lb-acceleration disabled)" native
M=$(cfgd bpf-lb-map-max 65536); R=$(cfgd bpf-map-dynamic-size-ratio 0.0025)
awk -v m="${M%\*}" -v r="${R%\*}" 'BEGIN{exit !(m>=131072 && r>=0.005)}' && out 12 "$M,$R" OK || out 12 "$M,$R" CHK
eq 13 "$(cfgd enable-bgp-control-plane false)" true
DV=$(cfgd devices auto); MT=$(cfgd mtu auto)
echo "$DV" | grep -q bond0 && echo "$DV" | grep -q bond1 && out 15 "$DV,mtu=$MT" OK || out 15 "$DV,mtu=$MT" CHK
out 16 "$(cfg ipam),$(cfg cluster-pool-ipv4-cidr),/$(cfg cluster-pool-ipv4-mask-size)" INFO
out 17 "$(cfg cluster-name),id=$(cfg cluster-id)" INFO
BW=$(cfgd enable-bandwidth-manager false); BB=$(cfgd enable-bbr false)
[ "${BW%\*}" = true ] && [ "${BB%\*}" = true ] && out 18 "bwm,bbr" OK || out 18 "bwm=$BW,bbr=$BB" CHK
out 19 "$(cfgd enable-ipv4-big-tcp false)" INFO
eq 20 "$(cfgd enable-ipv4-egress-gateway false)" true
out 21 "wg=$(cfgd enable-wireguard false)" INFO
out 22 "hubble=$(cfg enable-hubble),m=$(cfg hubble-metrics | cut -c1-30)" INFO
CM=$(cx cilium-dbg status | awk -F: '/^ClusterMesh/{sub(/^ +/,"",$2);print $2;exit}' | cut -c1-25)
if [ $K = 1 ]; then
  RP=$(kubectl -n kube-system get deploy clustermesh-apiserver -o jsonpath='{.spec.replicas}' 2>/dev/null)
  KV=$(kubectl -n kube-system get deploy clustermesh-apiserver -o jsonpath='{.spec.template.spec.containers[*].name}' 2>/dev/null | grep -q kvstoremesh && echo Y || echo N)
  out 23 "${CM:-?},rep=${RP:-0},kvs=$KV" INFO
else out 23 "${CM:-?}" INFO; fi

# ===== BGP (24 · 25 · 27)
P=$(cx cilium-dbg bgp peers | awk 'NR>1 && $0!~/^ *$/')
PN=$(echo "$P" | grep -c .); PE=$(echo "$P" | grep -ci established)
SN=$(echo "$P" | grep -oE '([0-9]+\.){3}[0-9]+' | awk -F. '{print $1"."$2"."$3}' | sort -u | grep -c .)
[ "$PN" -ge 4 ] && [ "$PE" = "$PN" ] && [ "$SN" -ge 2 ] && out 24 "p=$PN,est=$PE,sub=$SN" OK || out 24 "p=$PN,est=$PE,sub=$SN" CHK
if [ $K = 1 ]; then
  TM=$(kubectl get ciliumbgppeerconfig -o jsonpath='{range .items[*]}{.spec.timers.holdTimeSeconds}/{.spec.timers.keepAliveTimeSeconds}/{.spec.gracefulRestart.restartTimeSeconds} {end}' 2>/dev/null)
  echo "$TM" | grep -qE '^9/3/(60|[1-5][0-9]|[0-9])( |$)' && out 25 "$TM" OK || out 25 "${TM:-def}" CHK
else out 25 "-" NA; fi
AD=$(cx cilium-dbg bgp routes advertised ipv4 unicast | awk 'NR>1{print $1}' | sort | uniq -c | awk '{printf "%s:%s ",$2,$1}')
out 27 "$(echo $AD | cut -c1-40)" INFO

else for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 27; do out $n "cilium?" NA; done; fi

# ===== Service (28~33, kubectl 필요)
if [ $K = 1 ]; then
  PL=$(kubectl get ciliumloadbalancerippools --no-headers 2>/dev/null | wc -l)
  [ "$PL" -ge 2 ] && out 28 "pools=$PL" OK || out 28 "pools=$PL" CHK
  LB=$(kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.spec.externalTrafficPolicy} {.spec.sessionAffinity} {.spec.trafficDistribution}{"\n"}{end}')
  LO=$(echo "$LB" | grep -c '^Local'); CL=$(echo "$LB" | grep -c '^Cluster')
  [ "$LO" = 0 ] && out 29 "Cl=$CL,Lo=$LO" OK || out 29 "Cl=$CL,Lo=$LO" CHK
  CI=$(echo "$LB" | awk '$2=="ClientIP"' | grep -c .)
  [ "$CI" = 0 ] && out 30 "ClientIP=0" OK || out 30 "ClientIP=$CI" CHK
  YA=$(kubectl get svc -A -o yaml)
  TD=$(echo "$LB" | awk 'NF>=3' | grep -c .); TO=$(echo "$YA" | grep -c "topology-mode")
  [ "$TD" = 0 ] && [ "$TO" = 0 ] && out 31 "td=0,topo=0" OK || out 31 "td=$TD,topo=$TO" CHK
  MG=$(echo "$YA" | grep -c "service.cilium.io/lb-algorithm: maglev")
  [ "$MG" -ge 1 ] && out 32 "maglev=$MG" OK || out 32 "maglev=0" CHK
  GL=$(echo "$YA" | grep -c 'service.cilium.io/global: "true"'); AF=$(echo "$YA" | grep -c "service.cilium.io/affinity")
  [ "$GL" -ge 1 ] && [ "$AF" = 0 ] && out 33 "global=$GL,aff=$AF" OK || out 33 "global=$GL,aff=$AF" CHK
else for n in 28 29 30 31 32 33; do out $n "-" NA; done; fi

# ===== 노드 (37 · 39~49)
KV=$(uname -r); OSV=$(sed -E 's/.*release ([0-9.]+).*/\1/' /etc/redhat-release 2>/dev/null)
awk -v k="$KV" 'BEGIN{split(k,a,"[.-]"); exit !(a[1]>6 || (a[1]==6 && a[2]>=8))}' && out 37 "rhel$OSV,$(echo $KV|cut -d- -f1)" OK || out 37 "rhel$OSV,$(echo $KV|cut -d- -f1)" CHK
LR=""; MI=""; MTU=""
for b in bond0 bond1; do
  f=/proc/net/bonding/$b; [ -r $f ] || continue
  LR+="$(awk -F': ' '/LACP rate/{print $2;exit}' $f),"; MI+="$(awk -F': ' '/MII Polling Interval/{print $2;exit}' $f),"
  MTU+="$(cat /sys/class/net/$b/mtu),"
done
if [ -z "$MTU" ]; then out 39 "bond?" NA; out 40 "bond?" NA; else
[ "$LR" = "fast,fast," ] && [ "$MI" = "100,100," ] && out 39 "fast,100" OK || out 39 "${LR%,}/${MI%,}" CHK
[ "$MTU" = "9000,9000," ] && out 40 "9000" OK || out 40 "${MTU%,}" CHK
fi
eq 41 "$(sysctl -n net.ipv4.fib_multipath_hash_policy)" 1
RF=$(sysctl -n net.ipv4.conf.all.rp_filter); UN=$(sysctl -n net.ipv4.fib_multipath_use_neigh)
[ "$RF" != 1 ] && [ "$UN" = 1 ] && out 42 "rp=$RF,un=$UN" OK || out 42 "rp=$RF,un=$UN" CHK
CC=$(sysctl -n net.ipv4.tcp_congestion_control); QD=$(sysctl -n net.core.default_qdisc)
[ "$CC" = bbr ] && [ "$QD" = fq ] && out 43 "bbr,fq" OK || out 43 "$CC,$QD" CHK
RM=$(sysctl -n net.core.rmem_max); WM=$(sysctl -n net.core.wmem_max); BL=$(sysctl -n net.core.netdev_max_backlog)
awk -v r="$RM" -v w="$WM" -v b="$BL" 'BEGIN{exit !(r>=134217728 && w>=134217728 && b>=250000)}' && out 44 "ok" OK || out 44 "$((RM/1048576))M,$((WM/1048576))M,$BL" CHK
NICS=$(cat /sys/class/net/bond0/bonding/slaves /sys/class/net/bond1/bonding/slaves 2>/dev/null)
if [ -z "$NICS" ]; then for n in 45 46 47 48; do out $n "nic?" NA; done; else
DRV=$(for d in $NICS; do ethtool -i $d 2>/dev/null | awk '/^driver/{print $2}'; done | sort -u | tr '\n' ',')
out 45 "${DRV%,}" INFO
RG=OK; RGV=""; QV=""; LRO=OK
for d in $NICS; do
  read -r cur mx <<<"$(ethtool -g $d 2>/dev/null | awk '/Pre-set/{p=1} /Current/{p=2} /^RX:/{if(p==1)m=$2; else c=$2} END{print c, m}')"
  [ "$cur" = "$mx" ] || RG=CHK; RGV="${cur}/${mx}"
  q=$(ethtool -l $d 2>/dev/null | awk '/Combined/{v=$2} END{print v}'); nn=$(cat /sys/class/net/$d/device/numa_node 2>/dev/null)
  QV+="$q@n$nn,"
  ethtool -k $d 2>/dev/null | grep -q "large-receive-offload: on" && LRO=CHK
done
out 46 "$RGV" $RG
out 47 "$(echo ${QV%,} | tr ',' '\n' | sort -u | tr '\n' ',' | sed 's/,$//')" INFO
out 48 "$( [ $LRO = OK ] && echo off || echo on)" $LRO
fi
TU=$(tuned-adm active 2>/dev/null | awk -F': ' '{print $2}'); IB=$(systemctl is-active irqbalance 2>/dev/null); FW=$(systemctl is-active firewalld 2>/dev/null)
[ "$TU" = "network-throughput" ] && [ "$FW" != active ] && out 49 "tp,irq=$IB,fw=$FW" OK || out 49 "${TU:-none},irq=$IB,fw=$FW" CHK

echo "== 요약 (이 4줄만 보내면 됨. * = 기본값) =="
echo "OK  : ${OKS[*]}"
echo "CHK : ${CHKS[*]}"
echo "INFO: ${INFOS[*]}"
echo "NA  : ${NAS[*]}"
