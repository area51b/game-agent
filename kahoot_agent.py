import asyncio
import aiohttp
from datetime import datetime

# Kahoot imports
from kahoot import KahootClient
from kahoot.packets.impl.respond import RespondPacket
from kahoot.packets.server.game_over import GameOverPacket
from kahoot.packets.server.game_start import GameStartPacket
from kahoot.packets.server.question_end import QuestionEndPacket
from kahoot.packets.server.question_ready import QuestionReadyPacket
from kahoot.packets.server.question_start import QuestionStartPacket

client: KahootClient = KahootClient()

# Global dictionary to store predicted answers
predicted_answers = {}

def extract_answer_number(response_text: str, num_choices: int) -> int:
    """Extract answer choice number from Ollama response based on number of choices"""
    response_text = response_text.strip().lower()
    
    # For true/false questions
    if num_choices == 2:
        if response_text in ['0', '1']:
            return int(response_text)
        elif 'true' in response_text or 'correct' in response_text or 'yes' in response_text:
            return 0  # Assuming True is usually choice 0
        elif 'false' in response_text or 'incorrect' in response_text or 'no' in response_text:
            return 1  # Assuming False is usually choice 1
        else:
            # Try to find first number 0 or 1
            numbers = re.findall(r'[0-1]', response_text)
            if numbers:
                return int(numbers[0])
            return 0  # Default fallback
    
    # For multiple choice questions (4 options)
    else:
        if response_text in ['0', '1', '2', '3']:
            return int(response_text)
        
        numbers = re.findall(r'[0-3]', response_text)
        if numbers:
            return int(numbers[0])
        
        return 0  # Default fallback

async def download_image(url: str) -> bytes:
    """Download image from URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    print(f"Failed to download image: HTTP {response.status}")
                    return None
    except Exception as e:
        print(f"Error downloading image: {str(e)}")
        return None

async def get_ollama_answer(question: str, choices: list, image_url: str = None) -> int:
    """Get answer from local Ollama model"""
    try:
        # Build prompt based on number of choices
        if len(choices) == 2:
            # True/False question
            prompt = f"""You are a quiz AI. Only return the number of the correct answer.

Question: {question}

Answer choices:
0. {choices[0]}
1. {choices[1]}

Respond ONLY with 0 or 1 — no explanation."""
        else:
            # Multiple choice question (assume 4 choices, pad if needed)
            choices_padded = choices + [''] * (4 - len(choices))  # Pad to 4 if less
            prompt = f"""You are a quiz AI. Only return the number of the correct answer.

Question: {question}

Answer choices:
0. {choices_padded[0]}
1. {choices_padded[1]}
2. {choices_padded[2]}
3. {choices_padded[3]}

Respond ONLY with 0, 1, 2, or 3 — no explanation."""

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "gpt-oss:20b",
                    "prompt": prompt,
                    "stream": False
                },
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data.get("response", "").strip()
                    answer_choice = extract_answer_number(text, len(choices))
                    
                    # Validate answer choice is within range
                    if answer_choice >= len(choices):
                        answer_choice = 0
                    
                    print(f"Answer: {answer_choice} - {choices[answer_choice]}")
                    return answer_choice
                else:
                    print(f"Ollama API Error: {response.status}")
                    return 0
    except Exception as e:
        print(f"Error in get_ollama_answer: {str(e)}")
        return 0

async def game_start(packet: GameStartPacket):
    print(f"Game started: {packet}")
    predicted_answers.clear()

async def game_over(packet: GameOverPacket):
    print(f"Game over: {packet}")
    predicted_answers.clear()

async def question_ready(packet: QuestionReadyPacket):
    """Predict answer when question is ready"""
    try:
        content = packet.content
        question_text = content.get('title', 'Unknown question')
        choices_data = content.get('choices', [])
        question_number = content.get('gameBlockIndex', 0)
        image_url = content.get('image', None)

        choices = [choice.get('answer', f'Choice {i}') for i, choice in enumerate(choices_data)]

        print(f"Analyzing question {question_number}: {question_text}")
        if image_url:
            print(f"Question includes image: {image_url}")
        print(f"Choices ({len(choices)}): {choices}")

        predicted_answer = await get_ollama_answer(question_text, choices, image_url)
        predicted_answers[question_number] = predicted_answer

    except Exception as e:
        print(f"Error in question_ready: {str(e)}")
        try:
            question_number = packet.content.get('gameBlockIndex', 0)
        except:
            question_number = 0
        predicted_answers[question_number] = 0

async def question_start(packet: QuestionStartPacket):
    """Send the predicted answer"""
    print(f"[{datetime.now()}] question_start")
    try:
        question_number = packet.game_block_index
        answer_choice = predicted_answers.get(question_number, 0)

        await client.send_packet(
            RespondPacket(client.game_pin, answer_choice, question_number)
        )
        print(f"[{datetime.now()}] question_start completed")
        print(f"Answered question {question_number} with choice {answer_choice}")

    except Exception as e:
        print(f"Error: {str(e)}")

async def question_end(packet: QuestionEndPacket):
    print(f"Question ended: {packet}")

async def main():
    game_pin: int = int(input("Enter the game pin: "))
    name: str = input("Enter your name: ")

    client.on("game_start", game_start)
    client.on("game_over", game_over)
    client.on("question_start", question_start)
    client.on("question_end", question_end)
    client.on("question_ready", question_ready)

    await client.join_game(game_pin, name)

    print(f"Joined game {game_pin} as {name}")

if __name__ == "__main__":
    asyncio.run(main())
