import asyncio

from services import ConversationState, conversation


async def run():
  state = ConversationState()
  print('=' * 60)
  print('Procurement agent - keyboard harness')
  print('Type as the farmer. /quit to exit. /state to dump state anytime.')
  print('=' * 60)

  while True:
    user_input = input('\n[farmer] ').strip()

    if user_input in {'/quit', '/exit'}:
      break

    if user_input == '/state':
      print(state.summary())
      continue

    if not user_input:
      continue

    result = await conversation(user_input, state)
    state = result['state']

    print(f'\n[agent] {result["reply"]}')
    print('\n--- state ---')
    print(state.summary())

    if result['done']:
      print('\n' + '=' * 60)
      print('CALL DONE')
      print(f'Verdict: {state.qualification.verdict.value}')
      print(f'Reason: {state.qualification.reason}')

      if state.qualification.price:
        print(f'Target Price: {state.qualification.price.value} {state.qualification.price.unit}')

      print('=' * 60)
      break


if __name__ == '__main__':
  asyncio.run(run())
