let currentIndex = 0;
const slides = document.querySelectorAll(".slide");
function nextSlide()
{
    slides[currentIndex].style.display = 'none';
    currentIndex = (currentIndex + 1)% slides.length;
    slides[currentIndex].style.display = 'block';

}
setInterval(nextSlide,3000);
