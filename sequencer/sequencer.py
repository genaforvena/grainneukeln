import pygame

class SequencerController:

    def __init__(self):
        self.tempo = 160
        self.current_sample = 1
        self.sample_paths = {
            1: "",
            2: "",
            3: "",
            4: "",
            5: "",
            6: "",
            7: "",
            8: "",
        }
        self.sequences = {
            1: "",
            2: "",
            3: "",
            4: "",
            5: "",
            6: "",
            7: "",
            8: "",
        }
        self.playables = {
            1: None,
            2: None,
            3: None,
            4: None,
            5: None,
            6: None,
            7: None,
            8: None,
        }
        pygame.mixer.init()


    def __gen_playables(self, sample_number, sequence_number):
        if not self.sample_paths[sample_number]:
            return

        # Load the audio file
        audio = pygame.mixer.Sound(self.sample_paths[sample_number])

        # Set the tempo# Calculate the length of a beat in milliseconds based on the tempo
        tempo = 20
        beat_length = 60000 / tempo

        beats_per_minute = pygame.time.Clock()
        beats_per_minute.tick(tempo)

        # Create a list of beat times
        beat_times = [pygame.time.get_ticks()]

        # Set the number of beats in the sequence
        num_beats = 8

        # Add beat times to the list
        for i in range(num_beats - 1):
            beat_times.append(beat_times[-1] + beats_per_minute.get_time())

        # Transform the sequence into a list of true and false values
        sequence = self.sequences[sequence_number]
        sequence = [True if beat == "1" else False for beat in sequence]

        if not sequence:
            return

        # Play the sound at each beat time
        for beat_time in beat_times:
            if sequence[beat_time % len(sequence)]:
                audio.play()
            pygame.time.wait(100)  # Add a slight delay to avoid overlapping sounds


    def command(self, command = "help"):
        working = True
        while working:
            command = input(">>>")
            if command == "play":
                self.play_sequence()
            elif command == "stop":
                self.stop_sequence()
            elif command == "info":
                self.print_info()
            elif command.startswith("tempo"):
                self.set_tempo(command)
            elif command.startswith("sam"):
                self.set_sample(command)
            elif command.startswith("seq"):
                self.set_sequence(command)
            elif command == "help":
                self.print_help()
            elif command == "exit":
                working = False
                self.exit()
            else:
                print("Unknown command")

    def print_help(self):
        print("play - play the sequence")
        print("stop - stop the sequence")
        print("info - print the info")
        print("tempo - set the tempo")
        print("sample - set the sample")
        print("exit - exit the program")

    def print_info(self):
        print("Tempo: " + str(self.tempo))
        print("Sample paths: " + str(self.sample_paths))
        print("Sequence: " + str(self.sequences))

    def set_sample(self, command):
        if len(command.split(" ")) > 1:
            sample_number = int(command.split(" ")[1])
            if len(command.split(" ")) > 2:
                sample_path = command.split(" ")[2]
                self.sample_paths[sample_number] = sample_path
                self.__gen_playables(sample_number, sample_number)
            else:
                print("Unknown command")
        else:
            print("Unknown command")

    def set_sequence(self, command):
        if len(command.split(" ")) > 1:
            sequence_number = int(command.split(" ")[1])
            if len(command.split(" ")) > 2:
                sequence = command.split(" ")[2]
                self.sequences[sequence_number] = sequence
                self.__gen_playables(sequence_number, sequence_number)
            else:
                print("Unknown command")
        else:
            print("Unknown command")

    def set_tempo(self, command):
        if len(command.split(" ")) > 2:
            self.tempo = int(command.split(" ")[1])
        else:
            print("Unknown command")

    def play_sequence(self):
        # play the sequences in the order of the samples
        for sample_number in self.sample_paths:
            if self.playables[sample_number] is not None:
                sound = pygame.mixer.Sound(self.playables[sample_number])
                sound.play()
                pygame.time.wait(int(self.playables[sample_number].duration_seconds * 1000))

    def stop_sequence(self):
        pass

    def exit(self):
        print("Exiting the sequencer")
