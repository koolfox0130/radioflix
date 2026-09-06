FROM node:24-slim

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

ARG RADIOFLIX_API_URL=http://backend:8000
ENV RADIOFLIX_API_URL=${RADIOFLIX_API_URL}

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
