<div class="top"><div class="logo">Balanced<i>·</i>Portfolio</div>
<nav><b>指数估值</b><span>回测</span><span>构建</span><span>加密</span><span>方法论</span></nav>
<div class="r"><span>设计变体预览</span><span>2026-11-14</span></div></div>
<div class="shell"><div class="rail" id="rail"></div><div class="main" id="main"></div></div>
<div class="toggle"><b>涨跌色</b><div class="sw" id="sw"><span class="on" data-c="intl">绿涨红跌</span><span data-c="cn">红涨绿跌</span></div></div>
<script>
var R=[
["沪深300","000300",4016.29,-0.68,-14.58,20.47,15.77,2.10,13.63,2.61],
["中证500","000905",6465.48,-2.10,-12.10,30.61,59.04,2.29,57.76,1.47],
["中证1000","000852",6357.26,-2.76,-16.25,38.11,57.35,2.44,28.45,1.18],
["上证50","000016",2775.02,0.11,-9.72,18.64,61.05,2.15,52.08,2.92],
["创业板指","399006",2426.08,-3.32,-24.23,44.81,41.50,4.46,43.93,1.19],
["科创50","000688",1279.66,-2.30,-8.55,62.30,-1,6.06,-1,0.31],
["中证A500","000510",5321.44,-1.02,-11.22,17.92,8.31,1.98,7.42,2.88],
["中证红利","000922",5210.33,-0.44,-3.21,12.44,22.15,1.52,31.02,4.92],
["中证中药","930641",8458.56,-0.29,-17.82,23.27,13.68,2.02,2.72,3.68],
["中证白酒","399997",6808.51,2.03,-32.58,44.16,79.50,2.64,4.94,4.47],
["中证银行","399986",6120.44,0.32,8.41,6.92,71.20,0.68,44.10,4.12],
["中证医疗","399989",7210.11,-1.44,-21.05,27.17,8.96,2.88,3.21,0.72]
];
function spark(w,h,seed,color,fill){var p=[],y=50;for(var i=0;i<64;i++){y+=Math.sin(i/6+seed)*4+Math.cos(i/3.2+seed)*2;p.push(y)}var mn=Math.min.apply(null,p),mx=Math.max.apply(null,p);var d=p.map(function(v,i){return (i/(p.length-1)*w).toFixed(1)+","+(h-(v-mn)/((mx-mn)||1)*h).toFixed(1)}).join(" ");return "<svg width=\"100%\" viewBox=\"0 0 "+w+" "+h+"\" preserveAspectRatio=\"none\" style=\"display:block\">"+(fill?"<polygon points=\"0,"+h+" "+d+" "+w+","+h+"\" fill=\""+color+"\" opacity=\".09\"/>":"")+"<polyline points=\""+d+"\" fill=\"none\" stroke=\""+color+"\" stroke-width=\"1.6\"/></svg>"}
function pctCls(v){if(v==null||v===-1)return "mut";return v<30?"up":v>70?"down":"mut"}
function chg(v){return "<span class=\"num "+(v>=0?"up":"down")+"\">"+(v>=0?"+":"")+v+"%</span>"}
function rowHtml(r){var b="<tr><td><span class=\"nm\">"+r[0]+"</span><span class=\"cd\">"+r[1]+"</span></td><td class=\"num\">"+r[2].toLocaleString()+"</td><td>"+chg(r[3])+"</td>";return b+"<td class=\"num down\">"+r[4]+"%</td><td class=\"num\">"+r[5]+"</td><td class=\"num "+pctCls(r[6])+"\">"+(r[6]===-1?"-":r[6]+"%")+"</td><td class=\"num\">"+r[7]+"</td><td class=\"num "+pctCls(r[8])+"\">"+(r[8]===-1?"-":r[8]+"%")+"</td><td class=\"num\">"+r[9]+"%</td><td>"+chg(+(r[9]-1.61).toFixed(2))+"</td><td><span class=\"btn sm\">详情</span></td></tr>"}
function tbl(rows){return "<table><thead><tr><th>指数</th><th>收盘</th><th>涨跌</th><th>52周</th><th>PE</th><th>PE分位</th><th>PB</th><th>PB分位</th><th>股息率</th><th>风险溢价</th><th></th></tr></thead><tbody>"+rows.map(rowHtml).join("")+"</tbody></table>"}
var S={};