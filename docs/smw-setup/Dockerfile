FROM mediawiki:1.43

USER root

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && cp /var/www/html/composer.json /tmp/composer.json \
    && rm /var/www/html/composer.json \
    && cp /tmp/composer.json /var/www/html/composer.json \
    && composer require \
        mediawiki/semantic-media-wiki:'^6.0' \
        mediawiki/semantic-result-formats:'^5.0' \
        --working-dir=/var/www/html \
        --no-interaction \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
