---
parent: Usage
nav_order: 100
description: Speak with cecli about your code!
---

# Voice Mode

Speak with cecli about your code! Request new features, test cases or bug fixes using your voice and let cecli do the work of editing the files in your local git repo. As with all of cecli's capabilities, you can use voice-to-code with an existing repo or to start a new project.

Voice support fits quite naturally into cecli's AI assistance. You can fluidly switch between voice and text chat when you ask cecli to edit your code.

## How to use voice-to-code

Use the in-chat `/voice` command to start recording, and press `ENTER` when you're done speaking. Your voice coding instructions will be transcribed, as if you had  typed them into the cecli chat session.

See the [installation instructions](../install.html) for information on how to enable the `/voice` command.

> cecli v0.11.2-dev  
> Added app.py to the chat.  

#### /voice

> Recording, press ENTER when done... 3.5sec

> "add a factorial endpoint that uses math factorial"

#### Add a factorial endpoint that uses math.factorial.

To add a factorial endpoint to the Flask application, we need to modify the `app.py` file.

Here are the steps:

1. Add a new route `/fact/<int:x>` to the Flask application.
2. In the function for this route, call `math.factorial(x)` and return the result as a string.

Here is the *edit block* for these changes:

```python
app.py
<<<<<<< HEAD
if __name__ == '__main__':
    print("Starting...")
    app.run()
=======
@app.route('/fact/<int:x>')
def factorial(x):
    result = math.factorial(x)
    return str(result)

if __name__ == '__main__':
    print("Starting...")
    app.run()
>>>>>>> updated
```

> Applied edit to app.py  
> Commit ef9e3e7 cecli: Add a factorial endpoint that uses math.factorial.  
