FROM node:20-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json* /app/
RUN npm ci

COPY . /app

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "-p", "3000", "-H", "0.0.0.0"]
