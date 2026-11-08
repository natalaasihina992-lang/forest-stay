document.addEventListener("DOMContentLoaded", () => {
  const checkIn = document.querySelector('input[name="check_in"]');
  const checkOut = document.querySelector('input[name="check_out"]');
  const preview = document.getElementById("total-preview");

  if (checkIn && checkOut && preview && window.HOUSE_PRICE) {
    const update = () => {
      if (checkIn.value) {
        checkOut.min = checkIn.value;
        if (checkOut.value && checkOut.value <= checkIn.value) checkOut.value = "";
      }
      if (checkIn.value && checkOut.value) {
        const start = new Date(checkIn.value + "T00:00:00");
        const end = new Date(checkOut.value + "T00:00:00");
        const nights = Math.round((end - start) / 86400000);
        if (nights > 0) {
          preview.textContent = `${nights} ноч. · ${(nights * window.HOUSE_PRICE).toLocaleString("ru-RU")} ₽`;
        } else {
          preview.textContent = "Дата выезда должна быть позже заезда";
        }
      } else {
        preview.textContent = "Выберите даты для расчёта стоимости";
      }
    };
    checkIn.addEventListener("change", update);
    checkOut.addEventListener("change", update);
  }
});
