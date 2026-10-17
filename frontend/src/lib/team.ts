// Who built ComplAI. Each social icon in the navbar opens a menu listing both people.
// Leave a link empty ('') to hide that person from that menu; a network with no links is hidden.

export interface Person {
  name: string
  initials: string
  github: string
  linkedin: string
  discord: string // a profile link (https://discord.com/users/<id>) or a server invite
}

export const TEAM: Person[] = [
  {
    name: 'Muaaz Tariq',
    initials: 'MT',
    github: 'https://github.com/Prox1ty',
    linkedin: 'https://www.linkedin.com/feed/',
    discord: '',
  },
  {
    name: 'Muhammad Muizz Sajid',
    initials: 'MS',
    github: 'https://github.com/muizz-sajid',
    linkedin: 'https://www.linkedin.com/in/muhammad-muizz-sajid/',
    discord: '',
  },
]
