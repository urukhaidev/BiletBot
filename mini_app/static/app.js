const tg=window.Telegram?.WebApp;tg?.ready();tg?.expand();
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let dateMode='months',tripType='both',botName='dae110_bot',selectedMonths=new Set(),busy=false;
const initData=tg?.initData||'';
async function api(path,options={}){const response=await fetch('/mini-app/api/'+path,{...options,headers:{'Authorization':'tma '+initData,'Content-Type':'application/json',...options.headers}});const data=await response.json();if(!response.ok){const msg=Array.isArray(data.detail)?data.detail.map(d=>d.msg).join('; '):data.detail;throw new Error(msg||'Ошибка сервиса')}return data}
function status(message,error=false){$('#status').textContent=message;$('#status').className='status'+(error?' error':'')}
function openBot(){const url='https://t.me/'+botName;if(initData)tg.openTelegramLink(url);else window.open(url,'_blank','noopener')}
document.querySelectorAll('.to-bot').forEach(b=>b.onclick=openBot);
function syncFields(){$('#months-mode').classList.toggle('hidden',dateMode!=='months');$('#dates-mode').classList.toggle('hidden',dateMode==='months');$('#range-field').classList.toggle('hidden',dateMode!=='range');$('#return-field').classList.toggle('hidden',dateMode!=='dates'||tripType!=='RT');$('#duration-fields').classList.toggle('hidden',tripType==='OW'||(dateMode==='dates'&&tripType==='RT'&&$('#returning').value));}
$('#returning').onchange=syncFields;
$('#date-tabs').onclick=e=>{const b=e.target.closest('button');if(!b)return;dateMode=b.dataset.mode;$('#date-tabs .selected').classList.remove('selected');b.classList.add('selected');syncFields()};
$('#trip-tabs').onclick=e=>{const b=e.target.closest('button');if(!b)return;tripType=b.dataset.trip;$('#trip-tabs .selected').classList.remove('selected');b.classList.add('selected');syncFields()};
$('#swap').onclick=()=>{const a=$('#origin').value;$('#origin').value=$('#destination').value;$('#destination').value=a};
$('#months').onclick=e=>{const b=e.target.closest('button');if(!b)return;const m=b.dataset.month;if(selectedMonths.has(m))selectedMonths.delete(m);else{if(selectedMonths.size>=6){status('Можно выбрать до 6 месяцев',true);return}selectedMonths.add(m)}b.classList.toggle('selected',selectedMonths.has(m))};
async function loadConfig(){try{const c=await api('config');botName=c.bot_username;$('#open-bot').href='https://t.me/'+botName;const now=new Date(c.today+'T12:00:00');['departure','returning','range-end'].forEach(id=>$('#'+id).min=c.today);for(let i=0;i<12;i++){const d=new Date(now.getFullYear(),now.getMonth()+i,1);const m=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`;const b=document.createElement('button');b.type='button';b.className='month'+(i===0?' selected':'');b.dataset.month=m;b.innerHTML=esc(d.toLocaleDateString('ru-RU',{month:'long'}))+`<small>${d.getFullYear()}</small>`;$('#months').appendChild(b);if(i===0)selectedMonths.add(m)}}catch(e){status(e.message,true)}}
if(!initData){$('#outside').classList.remove('hidden');$('#submit').disabled=true}
loadConfig();
const closePlaceSuggestions={};
for(const id of ['origin','destination']){
  let timer,version=0,defaultsVersion=-1;
  const input=$('#'+id),options=$('#'+id+'-options');
  const buttons=places=>places.map(p=>`<button type="button" data-name="${esc(p.name)}">${esc(p.name)} <small>${p.country?esc(p.country)+' · ':''}${esc(p.code)}</small></button>`).join('');
  const close=()=>{clearTimeout(timer);version++;options.innerHTML=''};
  closePlaceSuggestions[id]=close;
  async function showDefaults(){
    if(defaultsVersion===version)return;
    close();
    for(const other of ['origin','destination'])if(other!==id)closePlaceSuggestions[other]?.();
    if(!initData)return;
    const current=version;
    defaultsVersion=current;
    try{
      const data=await api('place-suggestions?field='+id);
      if(current!==version||document.activeElement!==input)return;
      options.innerHTML=(data.recent.length?'<div class="suggestion-heading">Вы искали</div>'+buttons(data.recent):'')+'<div class="suggestion-heading">Популярные</div>'+buttons(data.popular);
    }catch{if(current===version)defaultsVersion=-1}
  }
  input.onclick=showDefaults;
  input.onfocus=showDefaults;
  input.oninput=()=>{
    close();
    const current=version,term=input.value.trim();
    if(!term){showDefaults();return}
    if(term.length<2||!initData)return;
    timer=setTimeout(async()=>{
      try{const places=await api('places?term='+encodeURIComponent(term));if(current!==version)return;options.innerHTML=buttons(places)}catch{}
    },200);
  };
  options.onclick=e=>{const b=e.target.closest('button');if(b){input.value=b.dataset.name;close()}};
}
document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete'))Object.values(closePlaceSuggestions).forEach(close=>close())});
function renderGroups(groups){$('#results').innerHTML=groups.map(g=>`<h2 class="result-heading">${g.trip_type==='OW'?'В одну сторону':'Туда-обратно'}${g.month?' · '+esc(new Date(g.month+'T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'})):''}</h2>`+(g.tickets.length?g.tickets.map(t=>`<article class="ticket"><div class="ticket-top"><div class="ticket-dates">${esc(t.departure)}${t.returning?'<br>'+esc(t.returning):''}</div><a class="ticket-price" href="${esc(t.url)}" target="_blank" rel="noopener">${t.price.toLocaleString('ru-RU')} ₽ ↗</a></div><div class="ticket-info">${esc(t.transfers)}<br>В пути ${esc(t.duration)}<br>${esc(t.baggage)}</div></article>`).join(''):'<div class="empty">Билеты не найдены. Попробуйте другие даты.</div>')).join('')+'<button class="primary" id="results-bot">Отслеживать цену в боте ↗</button>';$('#results-bot').onclick=openBot}
$('#search-form').onsubmit=async e=>{e.preventDefault();if(busy||!initData)return;const data={origin:$('#origin').value.trim(),destination:$('#destination').value.trim(),date_mode:dateMode,months:dateMode==='months'?[...selectedMonths]:[],departure:dateMode!=='months'?$('#departure').value||null:null,returning:dateMode==='dates'&&tripType==='RT'?$('#returning').value||null:null,range_end:dateMode==='range'?$('#range-end').value||null:null,trip_type:tripType,direct:$('#direct').checked,baggage:$('#baggage').checked,duration_min:Number($('#duration-min').value),duration_max:Number($('#duration-max').value)};if(dateMode==='months'&&!selectedMonths.size){status('Выберите месяц',true);return}busy=true;$('#submit').disabled=true;$('#results').innerHTML='';status('Ищем выгодные билеты… Результаты также отправим в бот.');try{const job=await api('search',{method:'POST',body:JSON.stringify(data)});let result;for(let i=0;i<240;i++){await new Promise(r=>setTimeout(r,1500));result=await api('search/'+job.job_id);if(result.status!=='running')break}if(result?.status==='error')throw new Error(result.error);if(result?.status!=='done')throw new Error('Поиск ещё выполняется. Результаты придут в бот.');renderGroups(result.groups);status(result.delivered?'Готово! Результаты отправлены и в Telegram.':'Билеты найдены. Отправка в бот не удалась — откройте бот и нажмите /start.');$('#status').scrollIntoView({behavior:'smooth',block:'start'});tg?.HapticFeedback?.notificationOccurred('success')}catch(e){status(e.message,true)}finally{busy=false;$('#submit').disabled=false}};
async function alerts(){try{const list=await api('alerts');$('#alerts-list').innerHTML=list.length?list.map(a=>`<article class="alert-card"><h3>${esc(a.route)}</h3><b>Дешевле ${a.threshold.toLocaleString('ru-RU')} ₽</b><p>${esc(a.query)}</p><button class="stop-alert" data-id="${a.id}">Остановить</button></article>`).join(''):'<div class="empty">Пока нет уведомлений.<br>Найдите билет и выберите цену в боте.</div>'}catch(e){$('#alerts-list').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
$('#alerts-list').onclick=async e=>{const b=e.target.closest('[data-id]');if(!b)return;b.disabled=true;try{await api('alerts/'+b.dataset.id,{method:'DELETE'});await alerts()}catch(e){b.disabled=false;tg?.showAlert?.(e.message)}};
async function profile(){try{const p=await api('profile');const name=[p.user.first_name,p.user.last_name].filter(Boolean).join(' ');$('#profile-content').innerHTML=`<div class="panel user-panel"><div class="avatar">${esc(name[0]||'✦')}</div><div><h2>${esc(name)}</h2><p>${p.user.username?'@'+esc(p.user.username):'Ваши путешествия начинаются здесь'}</p></div></div><div class="stats"><div class="stat"><b>${p.searches}</b><span>Поисков по условиям</span></div><div class="stat"><b>${p.alerts}</b><span>Активных алертов</span></div></div><div class="panel"><h2>Последние поиски</h2>${p.history.length?p.history.map(q=>`<div class="history-item">${esc(q)}</div>`).join(''):'<p class="hint">История пока пуста</p>'}</div>`}catch(e){$('#profile-content').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
document.querySelectorAll('.glass-nav button').forEach(b=>b.onclick=()=>{document.querySelector('.glass-nav .active').classList.remove('active');b.classList.add('active');document.querySelector('.page.active').classList.remove('active');$('#'+b.dataset.page).classList.add('active');window.scrollTo(0,0);if(b.dataset.page==='alerts')alerts();if(b.dataset.page==='profile')profile();tg?.HapticFeedback?.selectionChanged()});
