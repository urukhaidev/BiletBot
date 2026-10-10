for(const [id,label] of [['submit','Найти билеты'],['ai-submit','Найти с AI']]){
  const button=$('#'+id);
  button.innerHTML='<span class="search-star" aria-hidden="true">✦</span><span class="search-label"></span>';
  function refresh(){button.querySelector('.search-label').textContent=button.disabled&&initData?'Ищем билеты…':label;button.setAttribute('aria-busy',button.disabled&&initData?'true':'false')}
  new MutationObserver(refresh).observe(button,{attributes:true,attributeFilter:['disabled']});refresh();
}
