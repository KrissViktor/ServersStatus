(() => {
  for (const form of document.querySelectorAll('[data-group-editor]')) {
    const search = form.querySelector('[data-group-search]');
    const options = [...form.querySelectorAll('[data-group-option]')];
    function update() {
      const query = search.value.trim().toLocaleLowerCase('ru');
      let selected = 0, visible = 0;
      for (const option of options) {
        const input = option.querySelector('input');
        option.hidden = !option.textContent.toLocaleLowerCase('ru').includes(query);
        option.classList.toggle('is-selected', input.checked);
        selected += Number(input.checked);
        visible += Number(!option.hidden);
      }
      form.querySelector('[data-group-count]').textContent = `Выбрано: ${selected} из ${options.length}`;
      form.querySelector('[data-group-empty]').hidden = visible > 0 || options.length === 0;
    }
    search.addEventListener('input', update);
    form.addEventListener('change', update);
    for (const button of form.querySelectorAll('[data-group-select]')) {
      button.addEventListener('click', () => {
        for (const option of options) {
          if (!option.hidden) option.querySelector('input').checked = button.dataset.groupSelect === 'all';
        }
        update();
      });
    }
    update();
  }
})();
