document.addEventListener('DOMContentLoaded', function() {
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(message => {
        setTimeout(() => {
            message.style.opacity = '0';
            setTimeout(() => {
                message.remove();
            }, 500);
        }, 5000);
    });

    const postForm = document.querySelector('.post-form');
    if (postForm) {
        postForm.addEventListener('submit', function(event) {
            const contentField = this.querySelector('textarea[name="content"]');
            if (!contentField.value.trim()) {
                event.preventDefault();
                alert("Post cannot be empty!");
            }
        });

        const textarea = postForm.querySelector('textarea');
        const maxLength = textarea.getAttribute('maxlength');
        
        const charCounter = document.createElement('div');
        charCounter.classList.add('char-counter');
        charCounter.textContent = `0/${maxLength}`;
        textarea.parentNode.appendChild(charCounter);
        
        textarea.addEventListener('input', function() {
            const currentLength = this.value.length;
            charCounter.textContent = `${currentLength}/${maxLength}`;
            
            if (currentLength > maxLength * 0.8) {
                charCounter.classList.add('warning');
            } else {
                charCounter.classList.remove('warning');
            }
        });
    }

    function refreshPostTimers() {
        const posts = document.querySelectorAll('.post');
        const now = new Date();
        
        posts.forEach(post => {
            const postId = post.dataset.postId;
            const remainingSeconds = parseFloat(post.dataset.remainingSeconds);
            
            if (remainingSeconds < 60) {
                fetch(`/api/post/${postId}/remaining`)
                    .then(response => response.json())
                    .then(data => {
                        post.dataset.remainingSeconds = data.remaining_seconds;
                        
                        if (data.remaining_seconds <= 0) {
                            post.classList.add('vanishing');
                            setTimeout(() => {
                                post.remove();
                            }, 1000);
                        }
                    })
                    .catch(error => console.error('Error refreshing post timer:', error));
            }
        });
    }
    
    setInterval(refreshPostTimers, 60000);
});