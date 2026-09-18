FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
