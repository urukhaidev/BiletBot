const renderBeforePriceCalendar=renderGroups;
renderGroups=function(groups){
  renderBeforePriceCalendar(groups);
  const available=groups.filter(g=>g.search_id);
  if(!available.length)return;
  const panel=document.createElement('section');
  panel.className='panel price-calendar';
  panel.setAttribute('aria-label','Календарь цен');
  panel.innerHTML='<h2>Календарь цен</h2><label class="calendar-search-label">Направление и тип поездки<select class="calendar-search"></select></label><div class="calendar-navigation"><button type="button" class="calendar-prev" aria-label="Предыдущий месяц">‹</button><h3 class="calendar-month"></h3><button type="button" class="calendar-next" aria-label="Следующий месяц">›</button></div><div class="calendar-conditions hint"></div><div class="calendar-content" aria-live="polite"></div><p class="calendar-note hint">Минимальные цены из недавних поисков Aviasales. Багаж не учитывается. Итоговую цену и наличие уточняйте при переходе к билету.</p>';
  $('#results').appendChild(panel);
  const selector=panel.querySelector('.calendar-search'),content=panel.querySelector('.calendar-content');
  const title=panel.querySelector('.calendar-month'),previous=panel.querySelector('.calendar-prev'),next=panel.querySelector('.calendar-next');
  available.forEach((group,index)=>{
    const option=document.createElement('option');option.value=index;
    option.textContent=`${group.origin_name||''} — ${group.destination_name||''} · ${group.trip_type==='RT'?'Туда-обратно':'В одну сторону'}${group.month?' · '+new Date(group.month+'T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'}):''}`;
    selector.appendChild(option);
  });
  let currentMonth=null,today=null,version=0;
  const monthLabel=month=>new Date(month+'T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'});
  function shiftMonth(month,offset){const d=new Date(month+'T12:00:00');d.setMonth(d.getMonth()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`}
  async function load(month=null){
    const requestVersion=++version,group=available[Number(selector.value)];
    if(month)currentMonth=month;
    previous.disabled=true;next.disabled=true;
    title.textContent=month?monthLabel(month):'Загрузка…';
    content.innerHTML='<div class="calendar-message" role="status">Загружаем цены…</div>';
    panel.querySelector('.calendar-conditions').textContent='';
    try{
      const data=await api('calendar/'+group.search_id+(month?'?month='+encodeURIComponent(month):''));
      if(requestVersion!==version||!panel.isConnected)return;
      currentMonth=data.month;today=data.today;
      title.textContent=monthLabel(currentMonth);
      const conditions=[data.trip_type==='RT'?'Туда-обратно':'В одну сторону'];
      if(data.trip_type==='RT')conditions.push(data.returning?'Возврат '+new Date(data.returning+'T12:00:00').toLocaleDateString('ru-RU'):data.destination_name==='Куда угодно'?'Возврат в том же месяце':`Поездка на ${data.duration_min}–${data.duration_max} дней`);
      if(data.direct)conditions.push('Только прямые');else if(data.max_changes!=null)conditions.push('Пересадок: не больше '+data.max_changes);
      panel.querySelector('.calendar-conditions').textContent=conditions.join(' · ');
      const prices=new Map(data.days.map(day=>[day.date,day]));
      const minimum=data.days.length?Math.min(...data.days.map(day=>day.price)):null;
      const first=new Date(currentMonth+'T12:00:00'),offset=(first.getDay()+6)%7;
      const count=new Date(first.getFullYear(),first.getMonth()+1,0).getDate();
      content.innerHTML='<div class="calendar-grid">'+['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(day=>`<div class="calendar-weekday">${day}</div>`).join('')+'<div class="calendar-spacer" aria-hidden="true"></div>'.repeat(offset)+Array.from({length:count},(_,i)=>{
        const day=i+1,date=currentMonth.slice(0,8)+String(day).padStart(2,'0'),ticket=prices.get(date);
        const label=new Date(date+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'});
        if(!ticket)return `<div class="calendar-day calendar-unavailable${date<today?' calendar-past':''}" aria-label="${esc(label)}: ${date<today?'дата прошла':'нет данных о цене'}"><span>${day}</span><small>—</small></div>`;
        const price=ticket.price.toLocaleString('ru-RU'),details=(ticket.returning?' · Обратно '+new Date(ticket.returning+'T12:00:00').toLocaleDateString('ru-RU'):'')+(group.anywhere?' · '+ticket.destination:'');
        return `<a class="calendar-day${ticket.price===minimum?' calendar-cheapest':''}" href="${esc(ticket.url)}" target="_blank" rel="noopener" aria-label="${esc(label+': от '+price+' рублей'+details)}" title="${esc(label+details)}"><span>${day}</span><small>${price}</small></a>`;
      }).join('')+'</div>'+(minimum!==null?'<div class="calendar-legend"><span></span>Цены в ₽ · зелёным — самая низкая · нажмите на дату</div>':'<div class="calendar-message">На этот месяц пока нет цен по выбранным условиям. Попробуйте соседний месяц.</div>');
    }catch(error){
      if(requestVersion!==version||!panel.isConnected)return;
      content.innerHTML='<div class="calendar-message">'+esc(error.message)+'</div><button type="button" class="calendar-retry">Повторить загрузку</button>';
      content.querySelector('.calendar-retry').onclick=()=>load(month);
    }finally{
      if(requestVersion===version&&panel.isConnected){
        previous.disabled=!currentMonth||!today||currentMonth<=today.slice(0,7)+'-01';
        next.disabled=!currentMonth||!today||currentMonth>=`${Number(today.slice(0,4))+2}${today.slice(4,7)}-01`;
      }
    }
  }
  selector.onchange=()=>{currentMonth=null;load()};
  previous.onclick=()=>load(shiftMonth(currentMonth,-1));
  next.onclick=()=>load(shiftMonth(currentMonth,1));
  load();
};
