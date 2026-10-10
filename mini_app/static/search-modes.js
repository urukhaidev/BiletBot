let searchMode='form';
$('#date-picker').appendChild($('#duration-fields'));
const modeKey=draftKey+':mode',aiKey=draftKey+':ai';
function setSearchMode(mode){searchMode=mode;$('#search-form').classList.toggle('hidden',mode!=='form');$('#ai-form').classList.toggle('hidden',mode!=='ai');document.querySelectorAll('#search-mode-tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.searchMode===mode));try{localStorage.setItem(modeKey,mode)}catch{}}
$('#search-mode-tabs').onclick=e=>{const b=e.target.closest('[data-search-mode]');if(b)setSearchMode(b.dataset.searchMode)};
try{$('#ai-query').value=localStorage.getItem(aiKey)||'';setSearchMode(localStorage.getItem(modeKey)==='ai'?'ai':'form')}catch{}
$('#ai-query').oninput=()=>{try{localStorage.setItem(aiKey,$('#ai-query').value)}catch{}};
$('#ai-ideas').onclick=e=>{const b=e.target.closest('[data-query]');if(!b)return;const input=$('#ai-query');input.value=b.dataset.query;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();input.setSelectionRange(input.value.length,input.value.length);};
$('#add-return').onchange=()=>{$(`[data-trip="${$('#add-return').checked?'RT':'OW'}"]`).click();saveDraft();};
const oldSyncFields=syncFields;
syncFields=function(){
  if(dateMode==='dates')tripType=$('#returning').value?'RT':'OW';
  oldSyncFields();
  $('#return-field').classList.toggle('hidden',dateMode!=='dates');
  $('#add-return').closest('label').classList.toggle('hidden',dateMode==='dates');
  $('#duration-fields').classList.toggle('hidden',dateMode==='dates'||tripType==='OW');
  $('#add-return').checked=tripType==='RT';
  $('#return-hint').textContent='Укажите длительность поездки';
  $('#departure-label').textContent=dateMode==='range'?'Вылет от':'Вылет';
  document.querySelectorAll('#trip-tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.trip===tripType));
  $('#departure').disabled=dateMode==='months';
  $('#departure').required=dateMode!=='months';
  $('#returning').disabled=dateMode!=='dates';
  $('#range-end').disabled=dateMode!=='range';
  $('#range-end').required=dateMode==='range';
  for(const id of ['duration-min','duration-max'])$('#'+id).disabled=dateMode==='dates'||tripType==='OW';
};
$('#returning').onchange=()=>{syncFields();saveDraft();updateDateSummary()};
const originalApplyForm=applyForm;
applyForm=function(f){$('#returning').value=f.returning||'';originalApplyForm(f);setSearchMode(searchMode)};
const renderBeforeModes=renderGroups;
renderGroups=function(groups){renderBeforeModes(groups);$('#ai-form').classList.add('hidden');$('#search-mode-tabs').classList.add('hidden');const again=$('#search-again');again.onclick=()=>{$('#results').innerHTML='';$('#status').classList.add('hidden');$('.hero').classList.remove('hidden');$('#search-mode-tabs').classList.remove('hidden');again.classList.add('hidden');setSearchMode(searchMode);window.scrollTo(0,0)};};
$('#history-list').addEventListener('click',e=>{if(e.target.closest('[data-restore]')){$('#search-mode-tabs').classList.remove('hidden');setSearchMode('form')}});
const profileBeforeModes=profile;
profile=async function(){await profileBeforeModes();$('#profile-content .history-item')?.closest('.panel')?.remove();const panels=[...$('#profile-content .panel')];for(const panel of panels)if(panel.querySelector('h2')?.textContent==='Последние поиски')panel.remove();};
$('#ai-form').onsubmit=async e=>{e.preventDefault();if(busy||!initData)return;busy=true;$('#ai-submit').disabled=true;status('AI разбирает запрос и ищет билеты…');try{const job=await api('ai-search',{method:'POST',body:JSON.stringify({query:$('#ai-query').value.trim()})});let result;for(let i=0;i<240;i++){await new Promise(r=>setTimeout(r,1500));result=await api('search/'+job.job_id);if(result.status!=='running')break}if(result?.status==='error')throw new Error(result.error);if(result?.status!=='done')throw new Error('Поиск ещё выполняется. Результаты придут в бот.');renderGroups(result.groups);status(result.delivered?'Готово! Результаты также отправлены в Telegram.':'Результаты найдены, но не удалось отправить их в Telegram.');$('#status').scrollIntoView({behavior:'smooth'});}catch(e){status(e.message,true)}finally{busy=false;$('#ai-submit').disabled=false}};
