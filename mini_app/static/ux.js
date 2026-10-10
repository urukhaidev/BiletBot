document.querySelector('[data-search-mode="form"]').textContent='▤ Форма';
$('#ai-query').rows=2;
for(const input of document.querySelectorAll('input[type="date"]')){
  input.addEventListener('click',()=>{try{input.showPicker()}catch{}});
  input.closest('.field').addEventListener('click',e=>{if(e.target!==input){try{input.showPicker()}catch{input.focus()}}});
}
function setTheme(dark){document.documentElement.classList.toggle('dark',dark);$('#theme-toggle').innerHTML=dark?'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.5A9 9 0 0 1 9.5 3.5a9 9 0 1 0 11 11Z"/></svg>';$('#theme-toggle').setAttribute('aria-label',dark?'Светлая тема':'Тёмная тема');try{localStorage.setItem('biletbot-theme',dark?'dark':'light')}catch{}tg?.setHeaderColor?.(dark?'#101b2c':'#edf3fb');tg?.setBackgroundColor?.(dark?'#101b2c':'#edf3fb');}
try{setTheme(localStorage.getItem('biletbot-theme')==='dark')}catch{}
$('#theme-toggle').onclick=()=>setTheme(!document.documentElement.classList.contains('dark'));
const alertDialog=document.createElement('dialog');alertDialog.id='alert-dialog';alertDialog.innerHTML='<form id="alert-form"><h2>Отслеживать цену</h2><p id="alert-route"></p><div id="price-presets"></div><label for="alert-price">Уведомить, когда дешевле</label><input id="alert-price" type="number" min="1" max="999999" required inputmode="numeric" placeholder="Цена в рублях"><div id="alert-error" role="status"></div><button id="alert-save" class="primary" type="submit">Создать уведомление</button><button id="alert-cancel" type="button">Отмена</button></form>';document.body.appendChild(alertDialog);
let alertSearchId=null;
$('#alert-cancel').onclick=()=>alertDialog.close();
alertDialog.addEventListener('click',e=>{if(e.target===alertDialog)alertDialog.close()});
function openAlert(group){alertSearchId=group.search_id;$('#alert-route').textContent=group.query||'Выберите порог цены';$('#alert-error').textContent='';const min=group.tickets.length?Math.min(...group.tickets.map(t=>t.price)):null;$('#alert-price').value=min||'';$('#price-presets').innerHTML='';if(min)for(const ratio of [1,.95,.9,.8]){const price=Math.max(1,Math.round(min*ratio));const b=document.createElement('button');b.type='button';b.textContent=(ratio===1?'Текущая':`−${Math.round((1-ratio)*100)}%`)+` · ${price.toLocaleString('ru-RU')} ₽`;b.onclick=()=>$('#alert-price').value=price;$('#price-presets').appendChild(b)}alertDialog.showModal();}
$('#alert-form').onsubmit=async e=>{e.preventDefault();$('#alert-save').disabled=true;try{await api('alerts',{method:'POST',body:JSON.stringify({search_id:alertSearchId,price:Number($('#alert-price').value)})});alertDialog.close();status('Уведомление создано. Сообщим в Telegram, когда цена станет ниже выбранной.');tg?.HapticFeedback?.notificationOccurred('success')}catch(e){$('#alert-error').textContent=e.message}finally{$('#alert-save').disabled=false}};
const renderBeforeAlerts=renderGroups;
renderGroups=function(groups){renderBeforeAlerts(groups);$('#results').querySelectorAll('.track-result').forEach((b,i)=>{b.textContent='Отслеживать цены';b.onclick=()=>openAlert(groups[i])})};
$('#alerts .notice').textContent='Создавайте уведомления прямо под результатами поиска. Сообщения о снижении цены приходят в Telegram.';
