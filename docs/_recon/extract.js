(() => {
  const txt = el => (el && el.innerText || '').trim().replace(/\s+/g,' ');
  const heads = [...document.querySelectorAll('h1,h2,h3,h4')].slice(0,80).map(h=>h.tagName+':'+txt(h));
  const navs = [...document.querySelectorAll('header a, nav a')].slice(0,80).map(a=>txt(a)+' -> '+a.getAttribute('href'));
  const tables = [...document.querySelectorAll('table')].slice(0,4).map((t,i)=>({
    idx:i,
    headers:[...t.querySelectorAll('thead th')].map(txt),
    rows:t.querySelectorAll('tbody tr').length,
    firstRow:[...t.querySelectorAll('tbody tr')].slice(0,2).map(tr=>[...tr.children].map(c=>txt(c)))
  }));
  const links = [...document.querySelectorAll('a')].map(a=>a.getAttribute('href')).filter(Boolean);
  const uniqLinks = [...new Set(links)].filter(h=>!h.startsWith('http') || h.includes('etf.run')).slice(0,120);
  return JSON.stringify({title:document.title, heads, navs, tables, uniqLinks}, null, 1);
})()