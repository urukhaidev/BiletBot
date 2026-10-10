const renderWithFlow=renderGroups;
renderGroups=function(groups){
  renderWithFlow(groups);
  const headings=[...$('#results').querySelectorAll('.result-heading')];
  groups.forEach((group,i)=>{
    const route=document.createElement('div');
    route.className='result-route';
    route.textContent=group.origin_name&&group.destination_name
      ? group.origin_name+' — '+group.destination_name
      : group.query||($('#origin').value+' — '+$('#destination').value);
    headings[i].prepend(route);
  });
  groups.forEach((group,i)=>{
  const cards=[];
  for(let node=headings[i].nextElementSibling;node&&node!==headings[i+1];node=node.nextElementSibling)if(node.classList.contains('ticket'))cards.push(node);
  cards.forEach((card,index)=>{
    card.dataset.direct=String(group.tickets[index].direct??(group.tickets[index].transfers==='Прямой рейс'));
    if(card.dataset.direct==='true'){
      card.classList.add('direct-ticket');
      const info=card.querySelector('.ticket-info'),badge=document.createElement('span');
      badge.className='direct-badge';badge.textContent='Прямой рейс';
      if(info?.firstChild)info.replaceChild(badge,info.firstChild);
    }
  });
  const filters=document.createElement('div');
  filters.className='segmented result-filters';
  filters.setAttribute('aria-label','Фильтр рейсов');
  filters.innerHTML='<button type="button" class="selected" data-flight-filter="all" aria-pressed="true">Все</button><button type="button" data-flight-filter="direct" aria-pressed="false">Прямые</button>';
  const empty=document.createElement('div');empty.className='empty hidden';empty.textContent='Прямые рейсы по этим условиям не найдены.';
  headings[i].after(filters);filters.after(empty);
  filters.onclick=e=>{const button=e.target.closest('[data-flight-filter]');if(!button)return;const direct=button.dataset.flightFilter==='direct';filters.querySelectorAll('button').forEach(b=>{const selected=b===button;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected))});cards.forEach(card=>card.classList.toggle('hidden',direct&&card.dataset.direct!=='true'));empty.classList.toggle('hidden',!direct||cards.some(card=>card.dataset.direct==='true'));};
  });
};
