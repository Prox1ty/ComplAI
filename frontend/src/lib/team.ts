// Who built ComplAI. Each social icon in the navbar opens a menu listing both people.
// Leave a link empty ('') to hide that person from that menu; a network with no links is hidden.

export interface Person {
  name: string
  initials: string
  github: string
  linkedin: string
  discord: string // profile link: https://discord.com/users/<numeric user id>
  discordName: string // shown under the name in the menu
}

export const TEAM: Person[] = [
  {
    name: 'Muaaz Tariq',
    initials: 'MT',
    github: 'https://github.com/Prox1ty',
    linkedin: 'https://www.linkedin.com/in/muaaz-tariq-359715367/',
    discord: 'https://discord.com/users/608649430794764298',
    discordName: 'prox_109',
  },
  {
    name: 'Muhammad Muizz Sajid',
    initials: 'MS',
    github: 'https://github.com/muizz-sajid',
    linkedin: 'https://www.linkedin.com/in/muhammad-muizz-sajid/',
    discord: 'https://discord.com/users/553869981465706526',
    discordName: 'dark_phoenix5206',
  },
]
