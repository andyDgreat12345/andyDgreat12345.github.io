imgArray = ["images/group.jpg", "images/aaron.jpeg", "images/chairs.jpeg", "images/voting.jpeg"];
index = 0;
timer = 0;
function beginAutocycle()
{
    timer = setInterval(doNext,2500);
}
function doBack()
{
    if(index > 0)
    {
        index--;
    }
    else
    {
        index = imgArray.length - 1;
    }
    document.main_image.src = imgArray[index];
}
function doNext()
{
    if(index < imgArray.length - 1)
    {
        index++;
    }
    else
    {
        index = 0;
    }
    document.main_image.src = imgArray[index];
}
beginAutocycle()
function toTop()
{
    window.scrollTo({top: 0, behavior: 'smooth'});
}
function toggleVisibility()
{
    var button = document.getElementById('top_button')
    if (window.scrollY > 0)
    {
        button.style.visibility = 'visible';
    }
    else
    {
        button.style.visibility = 'hidden';
    }
}
document.addEventListener('DOMContentLoaded', toggleVisibility);
document.addEventListener('scroll', toggleVisibility)